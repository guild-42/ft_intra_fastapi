"""Test scaffolding.

The backend talks to Firestore (google-cloud-firestore), which isn't installed
in every environment. We stub the import surface that the repositories touch and
provide a tiny in-memory fake client so check-in logic can be unit-tested
without a real database or network.
"""
import sys
import types


def _ensure_firestore_stub():
    try:
        import google.cloud.firestore  # noqa: F401
        import google.cloud.firestore_v1.async_client  # noqa: F401
        return
    except Exception:
        pass

    google = sys.modules.setdefault("google", types.ModuleType("google"))
    cloud = sys.modules.setdefault("google.cloud", types.ModuleType("google.cloud"))
    google.cloud = cloud

    class _FieldFilter:
        def __init__(self, field, op, value):
            self.field, self.op, self.value = field, op, value

    class _Query:
        DESCENDING = "DESCENDING"
        ASCENDING = "ASCENDING"

    class _AsyncClient:  # only referenced for type hints / lazy construction
        pass

    firestore = types.ModuleType("google.cloud.firestore")
    firestore.AsyncClient = _AsyncClient
    firestore.FieldFilter = _FieldFilter
    firestore.Query = _Query
    sys.modules["google.cloud.firestore"] = firestore
    cloud.firestore = firestore

    fv1 = types.ModuleType("google.cloud.firestore_v1")
    async_client_mod = types.ModuleType("google.cloud.firestore_v1.async_client")
    async_client_mod.AsyncClient = _AsyncClient
    fv1.async_client = async_client_mod
    sys.modules["google.cloud.firestore_v1"] = fv1
    sys.modules["google.cloud.firestore_v1.async_client"] = async_client_mod


_ensure_firestore_stub()

from google.cloud import firestore as _fs  # noqa: E402

# DELETE_FIELD sentinel: present on the real lib; add it to the stub so repos
# that delete fields (clear_token / clear_user_tokens) work under the fake too.
if not hasattr(_fs, "DELETE_FIELD"):
    _fs.DELETE_FIELD = object()
_DELETE = _fs.DELETE_FIELD


# ───── in-memory fake Firestore ─────


class FakeSnap:
    def __init__(self, doc_id, data, ref):
        self.id = doc_id
        self._data = data
        self.reference = ref

    @property
    def exists(self):
        return self._data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class FakeDocRef:
    def __init__(self, store, coll, doc_id):
        self._store, self._coll, self._id = store, coll, doc_id

    async def get(self):
        data = self._store.get(self._coll, {}).get(self._id)
        return FakeSnap(self._id, data, self)

    async def set(self, doc, merge=False):
        coll = self._store.setdefault(self._coll, {})
        if merge and coll.get(self._id) is not None:
            merged = {**coll[self._id], **doc}
        else:
            merged = dict(doc)
        coll[self._id] = {k: v for k, v in merged.items() if v is not _DELETE}

    async def delete(self):
        self._store.get(self._coll, {}).pop(self._id, None)

    async def update(self, fields):
        coll = self._store.setdefault(self._coll, {})
        merged = {**(coll.get(self._id) or {}), **fields}
        coll[self._id] = {k: v for k, v in merged.items() if v is not _DELETE}


class FakeQuery:
    def __init__(self, store, coll, filters=None):
        self._store, self._coll, self._filters = store, coll, list(filters or [])

    def where(self, filter):
        return FakeQuery(self._store, self._coll, self._filters + [filter])

    def order_by(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    async def stream(self):
        for doc_id, data in list(self._store.get(self._coll, {}).items()):
            if data is None:
                continue
            ok = True
            for f in self._filters:
                if f.op == "==" and data.get(f.field) != f.value:
                    ok = False
                    break
            if ok:
                yield FakeSnap(
                    doc_id, data, FakeDocRef(self._store, self._coll, doc_id)
                )


class FakeCollection:
    def __init__(self, store, coll):
        self._store, self._coll = store, coll

    async def add(self, doc):
        coll = self._store.setdefault(self._coll, {})
        doc_id = f"auto{len(coll)}"
        coll[doc_id] = dict(doc)
        return None, FakeDocRef(self._store, self._coll, doc_id)

    def document(self, doc_id):
        return FakeDocRef(self._store, self._coll, str(doc_id))

    def where(self, filter):
        return FakeQuery(self._store, self._coll).where(filter)


class FakeClient:
    def __init__(self):
        self.store = {}

    def collection(self, name):
        return FakeCollection(self.store, name)
