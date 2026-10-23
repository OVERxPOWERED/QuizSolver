graph TB
    subgraph "External Systems"
        LMS[Canvas/Blackboard/Moodle LMS]
        GEMINI[Google Gemini API]
        NIM[NVIDIA NIM API]
        REDIS[Redis Cache]
    end

    subgraph "Quiz Automation Core"
        CLI[CLI Entry Point<br/>cli/main.py]
        
        subgraph "Orchestration Layer"
            QS[Quiz Service<br/>core/quiz_service.py]
            WS[Workflow Engine<br/>core/workflow.py]
        end
        
        subgraph "AI Layer"
            AS[AI Solver<br/>core/ai_solver.py]
            AP[Answer Parser<br/>core/answer_parser.py]
            VP[Vision Processor<br/>core/vision_processor.py]
        end
        
        subgraph "Browser Layer"
            BM[Browser Manager<br/>core/browser.py]
            PC[Page Controller<br/>core/page_controller.py]
            DE[DOM Extractor<br/>core/dom_extractor.py]
        end
        
        subgraph "Data Layer"
            CM[Cache Manager<br/>core/cache.py]
            DM[Database Manager<br/>core/database.py]
            SM[Schema Manager<br/>core/schema.py]
        end
        
        subgraph "Observability"
            PR[Profiler<br/>core/profiling.py]
            TL[Telemetry<br/>core/telemetry.py]
            LG[Structured Logger<br/>core/logging.py]
        end
    end

    subgraph "Persistence"
        DB[(SQLite Database<br/>data/quiz_bank.db)]
        RC[(Redis Cache<br/>Optional)]
    end

    CLI --> QS
    QS --> WS
    WS --> AS
    WS --> BM
    WS --> CM
    WS --> DM
    WS --> PR
    WS --> TL
    
    AS --> GEMINI
    AS --> NIM
    AS --> AP
    AS --> VP
    
    BM --> PC
    PC --> DE
    PC --> LMS
    
    CM --> REDIS
    CM --> DB
    DM --> DB
    SM --> DB
    
    PR --> TL
    TL --> LG