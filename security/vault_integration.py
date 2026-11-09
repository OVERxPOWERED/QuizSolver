# security/vault_integration.py
import os
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from pathlib import Path

import hvac
from hvac.exceptions import VaultError, InvalidRequest

logger = logging.getLogger(__name__)


@dataclass
class DatabaseCredentials:
    username: str
    password: str
    ttl: int
    lease_id: str
    renewable: bool
    issued_at: datetime

    @property
    def expires_at(self) -> datetime:
        return self.issued_at + timedelta(seconds=self.ttl)

    @property
    def should_renew(self) -> bool:
        elapsed = (datetime.utcnow() - self.issued_at).total_seconds()
        return elapsed >= (self.ttl * 0.8)


@dataclass
class AlertingSecrets:
    pagerduty_webhook_url: Optional[str]
    slack_webhook_url: Optional[str]
    pagerduty_routing_key: Optional[str]
    slack_bot_token: Optional[str]
    lease_id: str
    ttl: int
    issued_at: datetime


@dataclass
class MTLSCertificate:
    certificate: str
    private_key: str
    ca_chain: str
    serial_number: str
    ttl: int
    lease_id: str
    issued_at: datetime

    @property
    def expires_at(self) -> datetime:
        return self.issued_at + timedelta(seconds=self.ttl)

    @property
    def should_renew(self) -> bool:
        elapsed = (datetime.utcnow() - self.issued_at).total_seconds()
        return elapsed >= (self.ttl * 0.8)


class VaultClient:
    def __init__(
        self,
        vault_addr: str,
        vault_role: str,
        k8s_auth_path: str = "kubernetes",
        k8s_token_path: str = "/var/run/secrets/kubernetes.io/serviceaccount/token",
        namespace: Optional[str] = None,
        verify_ssl: bool = True,
        timeout: int = 30,
    ):
        self.vault_addr = vault_addr
        self.vault_role = vault_role
        self.k8s_auth_path = k8s_auth_path
        self.k8s_token_path = k8s_token_path
        self.namespace = namespace
        self.verify_ssl = verify_ssl
        self.timeout = timeout

        self._client: Optional[hvac.Client] = None
        self._auth_lock = threading.Lock()
        self._renewal_tasks: Dict[str, threading.Thread] = {}
        self._stop_renewal = threading.Event()
        self._renewal_lock = threading.Lock()

    def _create_client(self) -> hvac.Client:
        return hvac.Client(
            url=self.vault_addr,
            namespace=self.namespace,
            verify=self.verify_ssl,
            timeout=self.timeout,
        )

    def authenticate(self) -> bool:
        with self._auth_lock:
            if self._client and self._client.is_authenticated():
                return True

            self._client = self._create_client()

            try:
                token = self._read_k8s_token()
            except FileNotFoundError:
                logger.error("Kubernetes service account token not found at %s", self.k8s_token_path)
                return False
            except PermissionError:
                logger.error("Permission denied reading Kubernetes service account token")
                return False

            try:
                response = self._client.auth.kubernetes.login(
                    role=self.vault_role,
                    jwt=token,
                    mount_point=self.k8s_auth_path,
                )
                if not response.get("auth"):
                    logger.error("Vault Kubernetes authentication failed: no auth in response")
                    return False

                logger.info("Successfully authenticated with Vault using Kubernetes auth")
                return True

            except VaultError as e:
                logger.error("Vault authentication error: %s", e)
                return False
            except Exception as e:
                logger.error("Unexpected error during Vault authentication: %s", e)
                return False

    def _read_k8s_token(self) -> str:
        token_path = Path(self.k8s_token_path)
        if not token_path.exists():
            raise FileNotFoundError(f"Token file not found: {self.k8s_token_path}")
        return token_path.read_text().strip()

    def _ensure_authenticated(self) -> hvac.Client:
        if not self._client or not self._client.is_authenticated():
            if not self.authenticate():
                raise VaultError("Failed to authenticate with Vault")
        return self._client

    def get_database_credentials(self, role: str = "quizauto") -> DatabaseCredentials:
        client = self._ensure_authenticated()

        try:
            response = client.secrets.database.generate_credentials(
                name=role,
                mount_point="database",
            )

            data = response["data"]
            lease_id = response["lease_id"]
            lease_duration = response.get("lease_duration", 3600)
            renewable = response.get("renewable", True)

            creds = DatabaseCredentials(
                username=data["username"],
                password=data["password"],
                ttl=lease_duration,
                lease_id=lease_id,
                renewable=renewable,
                issued_at=datetime.utcnow(),
            )

            logger.info("Retrieved dynamic database credentials for role: %s", role)
            return creds

        except InvalidRequest as e:
            logger.error("Invalid request for database credentials: %s", e)
            raise
        except VaultError as e:
            logger.error("Vault error retrieving database credentials: %s", e)
            raise

    def get_alerting_secrets(self, path: str = "alerting", mount_point: str = "secret") -> AlertingSecrets:
        client = self._ensure_authenticated()

        try:
            response = client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point=mount_point,
            )

            data = response["data"]["data"]
            metadata = response["data"]["metadata"]

            lease_id = metadata.get("version", "kv-v2")
            ttl = 3600

            secrets = AlertingSecrets(
                pagerduty_webhook_url=data.get("pagerduty_webhook_url"),
                slack_webhook_url=data.get("slack_webhook_url"),
                pagerduty_routing_key=data.get("pagerduty_routing_key"),
                slack_bot_token=data.get("slack_bot_token"),
                lease_id=str(lease_id),
                ttl=ttl,
                issued_at=datetime.utcnow(),
            )

            logger.info("Retrieved alerting secrets from %s/%s", mount_point, path)
            return secrets

        except InvalidRequest as e:
            logger.error("Invalid request for alerting secrets: %s", e)
            raise
        except VaultError as e:
            logger.error("Vault error retrieving alerting secrets: %s", e)
            raise

    def get_mtls_certificate(
        self,
        role: str = "quizauto",
        common_name: Optional[str] = None,
        alt_names: Optional[str] = None,
        ip_sans: Optional[str] = None,
        mount_point: str = "pki",
    ) -> MTLSCertificate:
        client = self._ensure_authenticated()

        params: Dict[str, Any] = {}
        if common_name:
            params["common_name"] = common_name
        if alt_names:
            params["alt_names"] = alt_names
        if ip_sans:
            params["ip_sans"] = ip_sans

        try:
            response = client.secrets.pki.generate_certificate(
                name=role,
                mount_point=mount_point,
                **params,
            )

            data = response["data"]
            lease_id = response["lease_id"]
            lease_duration = response.get("lease_duration", 86400)

            cert = MTLSCertificate(
                certificate=data["certificate"],
                private_key=data["private_key"],
                ca_chain=data.get("ca_chain", [""])[0] if data.get("ca_chain") else "",
                serial_number=data["serial_number"],
                ttl=lease_duration,
                lease_id=lease_id,
                issued_at=datetime.utcnow(),
            )

            logger.info("Retrieved mTLS certificate for role: %s, serial: %s", role, cert.serial_number)
            return cert

        except InvalidRequest as e:
            logger.error("Invalid request for mTLS certificate: %s", e)
            raise
        except VaultError as e:
            logger.error("Vault error retrieving mTLS certificate: %s", e)
            raise

    def renew_lease(self, lease_id: str, increment: Optional[int] = None) -> int:
        client = self._ensure_authenticated()

        try:
            response = client.sys.renew_lease(lease_id=lease_id, increment=increment)
            new_ttl = response.get("lease_duration", 0)
            logger.info("Renewed lease %s, new TTL: %d seconds", lease_id, new_ttl)
            return new_ttl
        except VaultError as e:
            logger.error("Failed to renew lease %s: %s", lease_id, e)
            raise

    def revoke_lease(self, lease_id: str) -> bool:
        client = self._ensure_authenticated()

        try:
            client.sys.revoke_lease(lease_id=lease_id)
            logger.info("Revoked lease: %s", lease_id)
            return True
        except VaultError as e:
            logger.error("Failed to revoke lease %s: %s", lease_id, e)
            return False

    def start_background_renewal(
        self,
        lease_id: str,
        renew_callback: Optional[callable] = None,
        check_interval: int = 60,
    ) -> threading.Thread:
        def renewal_worker():
            while not self._stop_renewal.is_set():
                try:
                    time.sleep(check_interval)
                    if self._stop_renewal.is_set():
                        break

                    new_ttl = self.renew_lease(lease_id)
                    if renew_callback:
                        renew_callback(lease_id, new_ttl)

                    next_check = max(int(new_ttl * 0.8), check_interval)
                    time.sleep(next_check - check_interval)

                except Exception as e:
                    logger.error("Error in renewal worker for lease %s: %s", lease_id, e)
                    time.sleep(check_interval)

        thread = threading.Thread(target=renewal_worker, daemon=True, name=f"vault-renewal-{lease_id[:8]}")
        thread.start()

        with self._renewal_lock:
            self._renewal_tasks[lease_id] = thread

        logger.info("Started background renewal for lease: %s", lease_id)
        return thread

    def stop_background_renewal(self, lease_id: str) -> bool:
        with self._renewal_lock:
            if lease_id in self._renewal_tasks:
                self._stop_renewal.set()
                thread = self._renewal_tasks.pop(lease_id)
                thread.join(timeout=5)
                logger.info("Stopped background renewal for lease: %s", lease_id)
                return True
        return False

    def stop_all_renewals(self):
        self._stop_renewal.set()
        with self._renewal_lock:
            for lease_id, thread in self._renewal_tasks.items():
                thread.join(timeout=5)
            self._renewal_tasks.clear()
        logger.info("Stopped all background renewal tasks")

    def close(self):
        self.stop_all_renewals()
        if self._client:
            self._client = None
        logger.info("Vault client closed")

    def __enter__(self) -> "VaultClient":
        self.authenticate()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


class VaultConfig:
    def __init__(
        self,
        vault_addr: str,
        vault_role: str,
        k8s_auth_path: str = "kubernetes",
        k8s_token_path: str = "/var/run/secrets/kubernetes.io/serviceaccount/token",
        namespace: Optional[str] = None,
        verify_ssl: bool = True,
        timeout: int = 30,
    ):
        self.vault_addr = vault_addr
        self.vault_role = vault_role
        self.k8s_auth_path = k8s_auth_path
        self.k8s_token_path = k8s_token_path
        self.namespace = namespace
        self.verify_ssl = verify_ssl
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "VaultConfig":
        return cls(
            vault_addr=os.getenv("VAULT_ADDR", "http://vault:8200"),
            vault_role=os.getenv("VAULT_ROLE", "quizauto"),
            k8s_auth_path=os.getenv("VAULT_K8S_AUTH_PATH", "kubernetes"),
            k8s_token_path=os.getenv("VAULT_K8S_TOKEN_PATH", "/var/run/secrets/kubernetes.io/serviceaccount/token"),
            namespace=os.getenv("VAULT_NAMESPACE"),
            verify_ssl=os.getenv("VAULT_VERIFY_SSL", "true").lower() == "true",
            timeout=int(os.getenv("VAULT_TIMEOUT", "30")),
        )

    def create_client(self) -> VaultClient:
        return VaultClient(
            vault_addr=self.vault_addr,
            vault_role=self.vault_role,
            k8s_auth_path=self.k8s_auth_path,
            k8s_token_path=self.k8s_token_path,
            namespace=self.namespace,
            verify_ssl=self.verify_ssl,
            timeout=self.timeout,
        )
```