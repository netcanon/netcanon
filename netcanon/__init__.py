"""
netcanon — multi-vendor network configuration backup and translation engine.

Package layout
--------------
netcanon.config          Application settings (env-var driven via pydantic-settings).
netcanon.models          Domain models: DeviceTarget, BackupJob, ConfigRecord, etc.
netcanon.definitions     YAML definition loader and Pydantic schema.
netcanon.storage         Pluggable config storage (file-based v1).
netcanon.collectors      SSH collection strategies (Netmiko, Paramiko shell).
netcanon.migration       Canonical IR + per-vendor codecs + pipeline orchestrator.
netcanon.services        Cross-router business logic (migration pipeline, scheduler).
netcanon.tools           Operator-facing utilities (sanitiser, demo runner).
netcanon.api             FastAPI router modules.
netcanon.main            Application factory (create_app).

Entry point
-----------
Run the server:
    uvicorn netcanon.main:app --reload

Or programmatically (e.g. in tests):
    from netcanon.main import create_app
    from netcanon.config import Settings
    app = create_app(Settings(configs_dir=tmp_path))
"""
