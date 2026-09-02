# -*- coding: utf-8 -*-
"""The one place a Mongo connection is opened, and the one place it is kept read-only.

WHY A MODULE FOR THIS
  The credential in config.json is a read-only role, so a stray write would be refused by the
  server anyway. That is the wrong place to find out. A write that fails at the server fails
  inside a request handler, mid-collection, with half the facts gathered and a stack trace the
  user sees. This module makes the mistake impossible to write in the first place: coll() hands
  back a wrapper exposing exactly five read methods and nothing else in the app ever touches a
  pymongo Collection directly.
"""
import io
import json
import os

try:
    from pymongo import MongoClient, ReadPreference
except ImportError:  # pragma: no cover - START.bat installs this before we get here
    raise SystemExit(
        "pymongo is not installed.\n"
        "Run:  python -m pip install pymongo\n"
        "(START.bat normally does this for you.)"
    )

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CLIENT = None
_CFG = None


def config():
    """config.json, with MV_MONGO_URI and MV_GEMINI_KEY winning if they are set."""
    global _CFG
    if _CFG is None:
        with io.open(os.path.join(ROOT, "config.json"), encoding="utf-8") as fh:
            _CFG = json.load(fh)
        uri = os.environ.get("MV_MONGO_URI", "").strip()
        if uri:
            _CFG["mongo_uri"] = uri
        key = os.environ.get("MV_GEMINI_KEY", "").strip()
        if key:
            _CFG["ai"]["api_key"] = key
    return _CFG


class ReadOnlyCollection(object):
    """A pymongo Collection with only the read surface exposed.

    Attribute access is not forwarded. `c.insert_one` raises AttributeError here rather than
    reaching the server and raising OperationFailure there, which means the error lands at the
    line that is wrong instead of one layer down inside a driver.
    """

    __slots__ = ("_c", "name", "db_name")

    def __init__(self, coll, db_name):
        self._c = coll
        self.name = coll.name
        self.db_name = db_name

    def find(self, *a, **k):
        return self._c.find(*a, **k)

    def find_one(self, *a, **k):
        return self._c.find_one(*a, **k)

    def aggregate(self, pipeline, **k):
        for stage in pipeline:
            for op in ("$out", "$merge"):
                if op in stage:
                    raise PermissionError(
                        "%s is a WRITE stage and this client is read-only (%s.%s)"
                        % (op, self.db_name, self.name))
        k.setdefault("allowDiskUse", True)
        return self._c.aggregate(pipeline, **k)

    def count_documents(self, *a, **k):
        return self._c.count_documents(*a, **k)

    def distinct(self, *a, **k):
        return self._c.distinct(*a, **k)


def client():
    global _CLIENT
    if _CLIENT is None:
        cfg = config()
        _CLIENT = MongoClient(
            cfg["mongo_uri"],
            serverSelectionTimeoutMS=cfg.get("server_selection_timeout_ms", 12000),
            socketTimeoutMS=cfg.get("socket_timeout_ms", 180000),
            connectTimeoutMS=cfg.get("server_selection_timeout_ms", 12000),
            read_preference=ReadPreference.SECONDARY_PREFERRED,
            appname="mv-owner-alerts",
        )
    return _CLIENT


def coll(key):
    """A configured collection by its logical key, e.g. coll('production')."""
    spec = config()["collections"][key]
    return ReadOnlyCollection(client()[spec["db"]][spec["name"]], spec["db"])


def ping():
    """Prove the tunnel is up before the UI promises anything.

    A MongoClient constructor does not connect - it returns instantly and fails later, inside
    the first query, as a 12-second server-selection timeout. Without this the first thing a
    user with the VPN down sees is a spinner that hangs and then an error naming a collection,
    which reads like a data problem rather than a network one.
    """
    try:
        client().admin.command("ping")
        return True, "connected"
    except Exception as exc:
        return False, ("Cannot reach MongoDB. Check the VPN is up (ping 10.20.30.1) and the "
                       "URI in config.json.\nDetail: %s: %s" % (type(exc).__name__, exc))
