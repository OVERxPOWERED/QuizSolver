"""Universal Web Code Editor Controller for Monaco, CodeMirror, ACE, and Textarea."""

from playwright.async_api import Page
from core.detector import EditorType, UniversalDetector
from utils.helpers import human_delay
from utils.logger import log


class EditorController:
    """Controls code reading and injection into modern web-based code editors."""

    def __init__(self, page: Page):
        self.page = page

    async def get_current_code(self, editor_type: Optional[EditorType] = None) -> str:
        """Extract existing starter code or boilerplate from the editor."""
        ed_type = editor_type or await UniversalDetector.detect_editor_type(self.page)

        try:
            if ed_type == "monaco":
                code = await self.page.evaluate(
                    """() => {
                        if (window.monaco && window.monaco.editor && window.monaco.editor.getModels().length > 0) {
                            return window.monaco.editor.getModels()[0].getValue();
                        }
                        const el = document.querySelector('.monaco-editor');
                        if (el && el._codeEditor) {
                            return el._codeEditor.getValue();
                        }
                        const lines = Array.from(document.querySelectorAll('.view-line'));
                        if (lines.length > 0) {
                            return lines.map(l => l.innerText).join('\\n');
                        }
                        return '';
                    }"""
                )
                return code or ""

            elif ed_type == "codemirror":
                code = await self.page.evaluate(
                    """() => {
                        const cm5 = document.querySelector('.CodeMirror');
                        if (cm5 && cm5.CodeMirror) {
                            return cm5.CodeMirror.getValue();
                        }
                        const cm6 = document.querySelector('.cm-content');
                        if (cm6) {
                            return cm6.innerText;
                        }
                        return '';
                    }"""
                )
                return code or ""

            elif ed_type == "ace":
                code = await self.page.evaluate(
                    """() => {
                        const el = document.querySelector('.ace_editor');
                        if (el && window.ace) {
                            const editor = window.ace.edit(el);
                            return editor.getValue();
                        }
                        return '';
                    }"""
                )
                return code or ""

            elif ed_type == "textarea":
                textarea = self.page.locator("textarea[id*='code'], textarea[name*='code'], textarea.vpl_editor, textarea").first
                if await textarea.count() > 0:
                    return await textarea.input_value()

        except Exception as e:
            log.warning(f"Could not extract current code from editor: {e}")

        return ""

    async def set_code(self, code: str, editor_type: Optional[EditorType] = None) -> bool:
        """Inject complete code solution into active web editor."""
        ed_type = editor_type or await UniversalDetector.detect_editor_type(self.page)
        log.info(f"Injecting code ({len(code)} chars) into [bold cyan]{ed_type.upper()}[/bold cyan] editor...")

        success = False

        # 1. Monaco Editor (VSCode Web)
        if ed_type == "monaco":
            success = await self.page.evaluate(
                """(newCode) => {
                    try {
                        if (window.monaco && window.monaco.editor && window.monaco.editor.getModels().length > 0) {
                            window.monaco.editor.getModels()[0].setValue(newCode);
                            return true;
                        }
                        const el = document.querySelector('.monaco-editor');
                        if (el && el._codeEditor) {
                            el._codeEditor.setValue(newCode);
                            return true;
                        }
                    } catch (e) {
                        return false;
                    }
                    return false;
                }""",
                code,
            )

        # 2. CodeMirror (v5 and v6)
        elif ed_type == "codemirror":
            success = await self.page.evaluate(
                """(newCode) => {
                    try {
                        const cm5 = document.querySelector('.CodeMirror');
                        if (cm5 && cm5.CodeMirror) {
                            cm5.CodeMirror.setValue(newCode);
                            return true;
                        }
                        const cm6 = document.querySelector('.cm-content');
                        if (cm6 && cm6.cmView && cm6.cmView.view) {
                            const view = cm6.cmView.view;
                            view.dispatch({
                                changes: {from: 0, to: view.state.doc.length, insert: newCode}
                            });
                            return true;
                        }
                    } catch (e) {
                        return false;
                    }
                    return false;
                }""",
                code,
            )

        # 3. ACE Editor
        elif ed_type == "ace":
            success = await self.page.evaluate(
                """(newCode) => {
                    try {
                        const el = document.querySelector('.ace_editor');
                        if (el && window.ace) {
                            const editor = window.ace.edit(el);
                            editor.setValue(newCode, -1);
                            return true;
                        }
                    } catch (e) {
                        return false;
                    }
                    return false;
                }""",
                code,
            )

        # 4. Standard Textarea
        elif ed_type == "textarea":
            textarea = self.page.locator(
                "textarea[id*='code'], textarea[name*='code'], textarea.vpl_editor, textarea.coderunner-answer, textarea"
            ).first
            if await textarea.count() > 0:
                await textarea.fill(code)
                await textarea.dispatch_event("input")
                await textarea.dispatch_event("change")
                success = True

        # 5. Universal Fallback: Clipboard Paste / Keyboard Select All
        if not success:
            log.info("Using universal keyboard/clipboard fallback to inject code...")
            try:
                # Find any focusable editor element
                editor_elem = self.page.locator(
                    ".monaco-editor, .cm-content, .ace_editor, textarea[id*='code'], [role='code'], [contenteditable='true']"
                ).first
                if await editor_elem.count() > 0:
                    await editor_elem.click(force=True)
                    await human_delay(0.2, 0.4)
                    # Select all and fill or type
                    await self.page.keyboard.press("ControlOrMeta+A")
                    await self.page.keyboard.press("Backspace")
                    # Set value via clipboard or insert text
                    await self.page.keyboard.insert_text(code)
                    success = True
            except Exception as e:
                log.error(f"Fallback code injection error: {e}")

        if success:
            log.info("[bold green]✓ Successfully injected code into editor![/bold green]")
        else:
            log.warning("Could not automatically inject code into editor.")

        await human_delay(0.5, 1.0)
        return success
