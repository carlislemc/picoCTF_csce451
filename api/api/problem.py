""" Module for interacting with the problems """
import imp
import json

import api.common
import api.user
import api.team

from datetime import datetime
from api.common import validate, APIException, check
from voluptuous import Schema, Length, Required, Range
from pymongo.errors import DuplicateKeyError
from bson import json_util
from os.path import join, isfile

grader_base_path = "./graders"
check_graders_exist = True

submission_schema = Schema({
    Required("tid"): check(
        (0, "This does not look like a valid tid.", [str, Length(max=100)])),
    Required("pid"): check(
        (0, "This does not look like a valid pid.", [str, Length(max=100)])),
    Required("key"): check(
        (0, "This does not look like a valid key.", [str, Length(max=100)]))
})

problem_schema = Schema({
    Required("basescore"): check(
        (0, "Basescore must be a positive integer.", [int, Range(min=0)])),
    Required("category"): check(
        (0, "Category must be a string.", [str])),
    Required("desc"): check(
        (0, "The problem description must be a string.", [str])),
    Required("displayname"): check(
        (0, "The problem's display name must be a string.", [str])),
    Required("grader"): check(
        (0, "A grader does not exist at that path.", [
            lambda grader: not check_graders_exist or
            isfile(join(grader_base_path, grader))])),
    Required("threshold"): check(
        (0, "Threshold must be a positive integer.", [int, Range(min=0)])),

    "disabled": check(
        (0, "A problem's disabled state is either True or False.", [
            lambda disabled: type(disabled) == bool])),
    "autogen": check(
        (0, "A problem should either be autogenerated or not, True/False", [
            lambda autogen: type(autogen) == bool])),
    "relatedproblems": check(
        (0, "Related problems should be a list of related problems.", [list])),
    "pid": check(
        (0, "The problem's pid should be a string.", [str])),
    "weightmap": check(
        (0, "Weightmap should be a dict.", [dict])),
    "tags": check(
        (0, "Tags must be described as a list.", [list])),
    "hint": check(
        (0, "A hint must be a string.", [str])),

    "_id": check(
        (0, "Your problems should not already have _ids.", [lambda id: False]))
})

def insert_problem(problem):
    """
    Inserts a problem into the database. Does sane validation.

    Args:
        Problem dict.
        basescore: points awarded for completing the problem.
        category: problem's category
        desc: description of the problem.
        grader: path relative to grader_base_path
        threshold: Amount of points necessary for a team to unlock this problem.

        Optional:
        disabled: True or False. Defaults to False.
        hint: hint for completing the problem.
        pid: if you care to manually specify a pid
        tags: list of problem tags.
        relatedproblems: list of related problems.
        weightmap: problem's unlock weightmap
        autogen: Whether or not the problem will be auto generated.
    Returns:
        The newly created problem id.
        """

    db = api.common.get_conn()
    validate(problem_schema, problem)

    problem["disabled"] = problem.get("disabled", False)

    if problem.get("pid", None) is None:
        problem["pid"] = api.common.token()

    if len(search_problems({"pid": problem["pid"]}, {"displayname": problem["displayname"]})) > 0:
        raise APIException(0, None, "Problem with identical displayname or pid already exists.")

    db.problems.insert(problem)

    return problem["pid"]

def remove_problem(pid):
    """
    Removes a problem from the given database.

    Args:
        pid: the pid of the problem to remove.
    Returns:
        The removed problem object.
    """

    db = api.common.get_conn()
    problem = get_problem(pid=pid)

    db.problems.remove({"pid": pid})

    return problem

def set_problem_disabled(pid, disabled):
    """
    Updates a problem's availability.

    Args:
        pid: the problem's pid
        disabled: whether or not the problem should be disabled.
    Returns:
        The updated problem object.
    """
    return update_problem(pid, {"disabled": disabled})

def update_problem(pid, updated_problem):
    """
    Updates a problem with new properties.

    Args:
        pid: the pid of the problem to update.
        updated_problem: an updated problem object.
    Returns:
        The updated problem object.
    """

    db = api.common.get_conn()

    problem = get_problem(pid=pid)
    problem.update(updated_problem)

    validate(problem_schema, problem)

    db.problems.update({"pid": pid}, problem)

    return problem

def search_problems(*conditions):
    """
    Aggregates all problems that contain all of the given properties from the list specified.

    Args:
        conditions: multiple mongo queries to search.
    Returns:
        The list of matching problems.
    """

    db = api.common.get_conn()

    return list(db.problems.find({"$or": list(conditions)}))

def insert_problem_from_json(blob):
    """
    Converts json blob of problem(s) into dicts. Runs insert_problem on each one.
    See insert_problem for more information.

    Returns:
        A list of the created problem pids if an array of problems is specified.
    """

    result = json.loads(blob, default=json_util.default)

    if type(result) == list:
        return [insert_problem(problem) for problem in result]
    elif type(result) == dict:
        return insert_problem(result)
    else:
        raise APIException(0, "JSON blob does not appear to be a list of problems or a single problem.")

def grade_problem(pid, key, uid=None):
    """
    Grades the problem with its associated grader script.

    Args:
        uid: uid if provided
        pid: problem's pid
        key: user's submission
    Returns:
        A dict.
        correct: boolean
        points: number of points the problem is worth.
        message: message returned from the grader.
    """

    problem = get_problem(pid=pid)

    try:
        (correct, message) = imp.load_source(
            problem["grader"][:-3], join(grader_base_path, problem["grader"])
        ).grade(uid, key)
    except FileNotFoundError:
        raise APIException(0, None, "Problem {} grader is offline.".format(problem["pid"]))

    return {
        "correct": correct,
        "points": problem["basescore"],
        "message": message
    }

def submit_key(tid, pid, key, uid=None, ip=None):
    """
    User problem submission. Problem submission is inserted into the database.

    Args:
        tid: user's team id
        pid: problem's pid
        key: answer text
        uid: user's uid
    Returns:
        A dict.
        correct: boolean
        points: number of points the problem is worth.
        message: message returned from the grader.
    """

    db = api.common.get_conn()
    validate(submission_schema, {"tid": tid, "pid": pid, "key": key})

    if pid not in get_unlocked_pids(tid):
        raise APIException(0, None, "You can't submit flags to problems you haven't unlocked.")

    if pid in get_solved_pids(tid):
        raise APIException(0, None, "You have already solved this problem.")

    user = api.user.get_user(uid=uid)
    if user is None:
        raise APIException(0, None, "User submitting flag does not exist.")
    uid = user["uid"]

    result = grade_problem(pid, key, uid)

    problem = get_problem(pid=pid)

    submission = {
        'uid': uid,
        'tid': tid,
        'timestamp': datetime.now(),
        'pid': pid,
        'ip': ip,
        'key': key,
        'category': problem['category'],
        'correct': result['correct']
    }

    if key in [submission["key"] for submission in  get_submissions(tid=tid)]:
        raise APIException(0, None, "You or one of your teammates has already tried this solution.")

    db.submissions.insert(submission)

    return result

def get_submissions(pid=None, uid=None, tid=None, category=None):
    """
    Gets the submissions from a team or user.
    Optional filters of pid or category.

    Args:
        uid: the user id
        tid: the team id

        category: category filter.
        pid: problem filter.
    Returns:
        A list of submissions from the given entity
    """

    db = api.common.get_conn()

    match = {}

    if uid is not None:
      match.update({"uid": uid})
    elif tid is not None:
      match.update({"tid": tid})

    if pid is not None:
      match.update({"pid": pid})

    if category is not None:
      match.update({"category": category})

    return list(db.submissions.find(match))

def clear_all_submissions():
    """
    Removes all submissions from the database.
    """

    db = api.common.get_conn()
    db.submissions.remove()

def clear_submissions(uid=None, tid=None):
    """
    Clear submissions from a given team or user.

    Args:
        uid: the user's uid to clear from.
        tid: the team's tid to clear from.
    """

    db = api.common.get_conn()

    match = {}

    if uid is not None:
        match.update({"uid": uid})
    elif tid is not None:
        match.update({"tid": tid})
    else:
        raise APIException(0, None, "You must supply either a tid or uid")

    return db.submissions.remove(match)

def invalidate_submissions(pid=None, uid=None, tid=None):
    """
    Invalidates the submissions for a given problem. Can be filtered by uid or tid.
    Passing no arguments will invalidate all submissions.

    Args:
        pid: the pid of the problem.
        uid: the user's uid that will his submissions invalidated.
        tid: the team's tid that will have their submissions invalidated.
    """

    db = api.common.get_conn()

    match = {}

    if pid is not None:
        match.update({"pid": pid})

    if uid is not None:
        match.update({"uid": uid})
    elif tid is not None:
        match.update({"tid": tid})

    db.submissions.update(match, {"correct": False})

def reevaluate_submissions_for_problem(pid):
    """
    In the case of the problem or grader being updated, this will reevaluate all submissions.
    This will NOT work for auto generated problems.

    Args:
        pid: the pid of the problem to be reevaluated.
    Returns:
        A list of affected tids.
    """

    db = api.common.get_conn()

    problem = get_problem(pid=pid)

    keys = {}
    for submission in get_submissions(pid=pid):
        key = submission["key"]
        if key not in keys:
            result = grade_problem(pid, key)
            if result["correct"] != submission["correct"]:
                keys[key] = result["correct"]
            else:
                keys[key] = None

    for key, change in keys.items():
        if change is not None:
            db.submissions.update({"key": key}, {"correct": change}, multi=True)

def get_problem(pid=None, name=None, show_disabled=False):
    """
    Gets a single problem.

    Args:
        pid: The problem id
        name: The name of the problem
        show_disabled: Boolean indicating whether or not to show disabled problems.
    Returns:
        The problem dictionary from the database
    """

    db = api.common.get_conn()

    match = {"disabled": show_disabled}
    if pid is not None:
        match.update({'pid': pid})
    elif name is not None:
        match.update({'displayname': name})
    else:
        raise APIException(0, None, "Problem information not given")

    db = api.common.get_conn()
    problem = db.problems.find_one(match)

    if problem is None:
        raise APIException(0, None, "Could not find problem")

    return problem

def get_all_problems(category=None, show_disabled=False):
    """
    Gets all of the problems in the database.

    Args:
        category: Optional parameter to restrict which problems are returned
        show_disabled: Boolean indicating whether or not to show disabled problems.
    Returns:
        List of problems from the database
    """

    db = api.common.get_conn()

    match = {"disabled": show_disabled}
    if category is not None:
      match.update({'category': category})

    return list(db.problems.find(match))

def get_solved_pids(tid, category=None):
    """
    Gets the solved pids for a given team.

    Args:
        tid: The team id
        category: Optional parameter to restrict which problems are returned
    Returns:
        List of solved problem ids
    """

    return [sub['pid'] for sub in get_submissions(tid=tid, category=category) if sub['correct'] == True]


def get_solved_problems(tid, category=None):
    """
    Gets the solved problems for a given team.

    Args:
        tid: The team id
        category: Optional parameter to restrict which problems are returned
    Returns:
        List of solved problem dictionaries
    """

    return [get_problem(pid) for pid in get_solved_pids(tid, category)]

def get_unlocked_pids(tid, category=None):
    """
    Gets the unlocked pids for a given team.

    Args:
        tid: The team id
        category: Optional parameter to restrict which problems are returned
    Returns:
        List of unlocked problem ids
    """

    solved = get_solved_problems(tid, category)

    unlocked = []
    for problem in get_all_problems():
        if 'weightmap' not in problem or 'threshold' not in problem:
            unlocked.append(problem['pid'])
        else:
            weightsum = sum(problem['weightmap'].get(pid, 0) for pid in get_solved_pids(tid, category))
            if weightsum >= problem['threshold']:
                unlocked.append(problem['pid'])

    return unlocked

def get_unlocked_problems(tid, category=None):
    """
    Gets the unlocked problems for a given team.

    Args:
        tid: The team id
        category: Optional parameter to restrict which problems are returned
    Returns:
        List of unlocked problem dictionaries
    """

    return [get_problem(pid) for pid in get_unlocked_pids(tid, category)]
