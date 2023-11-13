"""Caching Library using redis."""

import logging
from functools import wraps

from flask import current_app
from walrus import Walrus

import api
import hashlib
import pickle
from api import PicoException

log = logging.getLogger(__name__)

__redis = {
    "walrus": None,
    "cache": None,
    "zsets": {"scores": None},
}


def get_conn():
    """Get a redis connection, reusing one if it exists."""
    global __redis
    if __redis.get("walrus") is None:
        conf = current_app.config
        try:
            __redis["walrus"] = Walrus(
                host=conf["REDIS_ADDR"],
                port=conf["REDIS_PORT"],
                password=conf["REDIS_PW"],
                db=conf["REDIS_DB_NUMBER"],
            )
        except Exception as error:
            raise PicoException(
                "Internal srver error. " + "Please contact a system administrator.",
                data={"original_error": error},
            )
    return __redis["walrus"]


def get_cache():
    """Get a walrus cache, reusing one if it exists."""
    global __redis
    if __redis.get("cache") is None:
        __redis["cache"] = get_conn().cache(default_timeout=0)
    return __redis["cache"]


def get_score_cache():
    global __redis
    if __redis["zsets"].get("scores") is None:
        __redis["zsets"]["scores"] = get_conn().ZSet("scores")
    return __redis["zsets"]["scores"]


def get_scoreboard_cache(**kwargs):
    global __redis
    scoreboard_name = "scoreboard:{}".format(_hash_key((), kwargs))
    if __redis["zsets"].get(scoreboard_name) is None:
        __redis["zsets"][scoreboard_name] = get_conn().ZSet(scoreboard_name)
    return __redis["zsets"][scoreboard_name]


def clear():
    global __redis
    if __redis.get("walrus") is not None:
        __redis["walrus"].flushdb()


def __insert_cache(f, *args, **kwargs):
    """
    Directly upserting without first invalidating, thus keeping a memoized
    value available without lapse
    """
    if f == api.stats.get_score:
        raise PicoException("Error: Do not manually reset_cache get_score")
    else:
        key = "%s:%s" % (f.__name__, _hash_key(args, kwargs))
        value = f(*args, **kwargs)
        get_cache().set(key, value)
        return value


def memoize(_f=None, **cached_kwargs):
    """walrus.Cache.cached wrapper that reuses shared cache."""

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if kwargs.get("reset_cache", False):
                kwargs.pop("reset_cache", None)
                return __insert_cache(f, *args, **kwargs)
            else:
                return get_cache().cached(**cached_kwargs)(f)(*args, **kwargs)

        return wrapper

    if _f is None:
        return decorator
    else:
        return decorator(_f)


def _hash_key(a, k):
    return hashlib.md5(pickle.dumps((a, k))).hexdigest()


def get_scoreboard_key(team):
    # For lack of better idea of delimiter, use '>' illegal team name char
    return "{}>{}>{}".format(team["team_name"], team["affiliation"], team["tid"])


def decode_scoreboard_item(item, with_weight=False, include_key=False):
    """
    :param item: tuple of ZSet (key, score)
    :param with_weight: keep decimal weighting of score, or return as int
    :param include_key: whether to include to raw key
    :return: dict of scoreboard item
    """
    key = item[0].decode("utf-8")
    data = key.split(">")
    score = item[1]
    if not with_weight:
        score = int(score)
    output = {"name": data[0], "affiliation": data[1], "tid": data[2], "score": score}
    if include_key:
        output["key"] = key
    return output


def search_scoreboard_cache(scoreboard, pattern):
    """
    :param scoreboard: scoreboard cache ZSet
    :param pattern: text pattern to search team names and affiliations,
                    not including wildcards
    :return: sorted list of scoreboard entries
    """
    # Trailing '*>' avoids search on last token, tid
    results = [
        decode_scoreboard_item(item, with_weight=True, include_key=True)
        for item in list(scoreboard.search("*{}*>*".format(pattern)))
    ]
    return sorted(results, key=lambda item: item["score"], reverse=True)


def invalidate(f, *args, **kwargs):
    """
    Clunky way to replicate busting behavior due to awkward wrapping of walrus
    cached decorator
    """
    if f == api.stats.get_score:
        key = args[0]
        get_score_cache().remove(key)
    else:
        key = "%s:%s" % (f.__name__, _hash_key(args, kwargs))
        get_cache().delete(key)
