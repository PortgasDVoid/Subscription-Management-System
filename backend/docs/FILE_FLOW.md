# File flow

Two views: (1) who imports whom, (2) what runs in what order. GitHub, GitLab and VS Code
(Markdown Preview Mermaid Support) render these.

## 1. Code dependencies (arrow = "imports / calls")

```mermaid
flowchart TB
    subgraph DB["db/ (PostgreSQL 16)"]
        S1["01_schema.sql<br/>29 tables, triggers, views"]
        S2["02_seed.sql<br/>demo catalog + history"]
        S3["03_subscription_stage_view.sql"]
        S4["04_quick_checks.sql"]
        S1 --> S2 --> S3
    end

    subgraph UTIL["app/utils"]
        CALC["calculations.py<br/>money, tax, discount, period maths"]
    end

    subgraph REPO["app/repositories (SQL only)"]
        RB["billing_repository.py"]
        RP["payment_repository.py"]
        RL["lifecycle_repository.py"]
    end

    subgraph SVC["app/services"]
        ERR["errors.py"]
        PRC["pricing_service.py"]
        TAX["tax_service.py"]
        DSC["discount_service.py"]
        INV["invoice_service.py<br/>run_billing()"]
        PAY["payment_service.py"]
        LIFE["subscription_lifecycle_service.py<br/>run_lifecycle()"]
        PDF["pdf_service.py<br/>generate_invoice_pdf()"]
    end

    DBM["app/db.py<br/>engine + scope()"]

    PRC --> RB & CALC & ERR
    TAX --> RB & CALC & ERR
    DSC --> RB & CALC & ERR
    INV --> PRC & TAX & DSC & RB & CALC & ERR
    PAY --> RP & CALC & ERR
    LIFE --> RL & CALC & ERR
    PDF --> ERR

    RB & RP & RL -. SQL .-> S1

    subgraph SCR["scripts"]
        SEED["seed_database.py"]
        BENCH["benchmark_queries.py"]
    end
    SEED --> INV & CALC & DBM
    BENCH --> DBM
    DBM -.-> S1

    subgraph TST["tests"]
        T1["test_calculations / test_seed_plan / test_pdf (no DB)"]
        T2["test_invoice / test_payment_* / test_lifecycle_* (PostgreSQL)"]
        CF["conftest.py"]
    end
    T1 -.-> CALC & PDF & SEED
    T2 -.-> INV & PAY & LIFE
    CF -.-> S1
    CF -.-> S2

    API["api/invoice_routes.py + main.py<br/>NOT BUILT YET"]:::todo
    API -.-> PDF & INV & PAY
    classDef todo stroke-dasharray: 5 5,fill:#fff7e6,stroke:#b54708
```

## 2. Runtime order

```mermaid
flowchart LR
    A["01_schema.sql + 02_seed.sql"] --> B["seed_database.py<br/>customers, subscriptions"]
    B --> C["run_billing()<br/>confirmed invoices"]
    C --> D["payments + allocations<br/>triggers set paid / part-paid"]
    D --> E["mark_overdue_invoices()"]
    E --> F["benchmark_queries.py<br/>p95 vs 2 s"]
    E --> G["generate_invoice_pdf()"]

    subgraph NIGHT["Nightly (Celery)"]
        N1["run_billing()"] --> N2["run_lifecycle()<br/>renew or close expired"] --> N3["mark_overdue_invoices()"]
    end
```
