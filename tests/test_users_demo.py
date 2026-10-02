from interview_app.applications import get_application, list_applications
from interview_app.config import Limits
from interview_app.demo import load_sample_application
from interview_app.ingest import DocKind
from interview_app.users import ensure_local_user


def test_local_user_is_created_once(engine):
    first = ensure_local_user(engine)
    assert ensure_local_user(engine) == first


def test_sample_application_loads_with_all_documents(engine):
    user_id = ensure_local_user(engine)
    app_id = load_sample_application(engine, user_id, limits=Limits())
    detail = get_application(engine, user_id, app_id)
    assert set(detail.documents) == set(DocKind)
    assert [a.id for a in list_applications(engine, user_id)] == [app_id]
