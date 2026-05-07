import pytest
import shutil
from api.app import create_app
from api.extensions import db as _db


@pytest.fixture(scope="session")
def app():
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "DATA_DIR": "/tmp/scriptwatch-test-data",
        "SCRIPT_STORE_DIR": "/tmp/scriptwatch-test-data/script-store",
        "AGENT_TOKEN": "test-agent-token",
        "SECRET_KEY": "test-secret",
    })
    with app.app_context():
        _db.create_all()
        yield app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def clean_db(app):
    with app.app_context():
        _db.session.remove()
    yield
    with app.app_context():
        _db.session.remove()
        for table in reversed(_db.metadata.sorted_tables):
            _db.session.execute(table.delete())
        _db.session.commit()
        _db.session.remove()
    shutil.rmtree("/tmp/scriptwatch-test-data/script-store", ignore_errors=True)
