"""
netconfig — multi-vendor network configuration backup and translation engine.

Package layout
--------------
netconfig.config          Application settings (env-var driven via pydantic-settings).
netconfig.models          Domain models: DeviceTarget, BackupJob, ConfigRecord, etc.
netconfig.definitions     YAML definition loader and Pydantic schema.
netconfig.storage         Pluggable config storage (file-based v1).
netconfig.collectors      SSH collection strategies (Netmiko, Paramiko shell).
netconfig.api             FastAPI router modules.
netconfig.main            Application factory (create_app).

Entry point
-----------
Run the server:
    uvicorn netconfig.main:app --reload

Or programmatically (e.g. in tests):
    from netconfig.main import create_app
    from netconfig.config import Settings
    app = create_app(Settings(configs_dir=tmp_path))
"""
