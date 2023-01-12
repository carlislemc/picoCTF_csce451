"""Stores and retrieves runtime settings from the database."""

import datetime
from copy import deepcopy
from functools import wraps

import api
from api import PicoException

"""
Default Settings

These are the default settings that will be loaded
into the database if no settings are already loaded.
"""
default_settings = {
    "enable_feedback": True,
    # TIME WINDOW
    "start_time": datetime.datetime.utcnow(),
    "end_time": datetime.datetime.utcnow(),
    # COMPETITION INFORMATION
    "competition_name": "CSCE465",
    "competition_url": "http://192.168.2.2",
    "admin_email": "email@example.com",  # Contact given to parents
    # EMAIL WHITELIST
    "email_filter": [],
    # TEAMS
    "max_team_size": 5,
    # BATCH REGISTRATION
    "max_batch_registrations": 250,  # Maximum batch registrations / teacher
    # ACHIEVEMENTS
    "achievements": {
        "enable_achievements": True,
        "processor_base_path": "./achievements",
    },
    "username_blacklist": [
        "adm",
        "admin",
        "audio",
        "backup",
        "bin",
        "cdrom",
        "competitors",
        "crontab",
        "daemon",
        "dialout",
        "dip",
        "disk",
        "dnsmasq",
        "fax",
        "floppy",
        "games",
        "gnats",
        "hacksports",
        "input",
        "irc",
        "kmem",
        "list",
        "lp",
        "lxd",
        "mail",
        "man",
        "messagebus",
        "mlocate",
        "netdev",
        "news",
        "nobody",
        "nogroup",
        "operator",
        "plugdev",
        "pollinate",
        "proxy",
        "root",
        "sasl",
        "shadow",
        "shellinabox",
        "src",
        "ssh",
        "sshd",
        "staff",
        "sudo",
        "sync",
        "sys",
        "syslog",
        "tape",
        "tty",
        "ubuntu",
        "users",
        "utmp",
        "uucp",
        "uuidd",
        "vagrant",
        "vboxadd",
        "vboxsf",
        "video",
        "voice",
        "wetty",
    ],
    # EMAIL (SMTP)
    "email": {
        "enable_email": False,
        "email_verification": False,
        "parent_verification_email": True,
        "smtp_url": "",
        "smtp_port": 587,
        "email_username": "",
        "email_password": "",
        "from_addr": "",
        "from_name": "",
        "max_verification_emails": 3,
        "smtp_security": "TLS",
        "reset_password_body": """
We recently received a request to reset the password for the following {competition_name} account:

\t{username}

Our records show that this is the email address used to register the above account.
If you did not request to reset the password for the above account then you need not take any further steps.
If you did request the password reset please follow the link below to set your new password.

{competition_url}/reset#{token_value}

Best of luck!
The {competition_name} Team""",  # noqa (79char)
        ############ Readablity spacing ############
        "verification_body": """
Welcome to {competition_name}!

Your account has been registered with username {user_name}. You will need to
visit the verification link below and then login to finalize your account's
creation.

If you believe this to be a mistake, and you haven't recently created an account
for {competition_name} then you can safely ignore this email.

Verification link: {verification_link}

Good luck and have fun!
The {competition_name} Team""",  # noqa (79char)
        ############ Readablity spacing ############
        "verification_parent_body": """
Welcome to {competition_name}!

Your child or your child's teacher registered to participate in picoCTF, an
online cyber security capture-the-flag competition created for educational
purposes. Please see picoCTF.com for details about the competition.  picoCTF
is developed by Carnegie Mellon University faculty, staff and students.

A user account has just been created on our platform and your email address was
submitted by the user as the email address of the user's parent.

Thank you for authorizing the participation of your child age 13-17 in
{competition_name} and providing your email address as part of the account registration process
for your child. As a reminder, the Terms of Service, Privacy Statement and
Competition Rules for {competition_name} can be found at {competition_url}.

If you received this email in error because you did not authorize your child's
registration for {competition_name}, you are not the child's parent or legal guardian,
or your child is under age 13, please email us immediately at {admin_email}.

The {competition_name} Team""",  # noqa (79char)
        ############ Readablity spacing ############
        "invite_body": """
You have been invited by the teacher of classroom {group_name} to compete in {competition_name}.
You will need to follow the registration link below to finish the account creation process.

If you believe this to be a mistake you can safely ignore this email.

Registration link: {registration_link}

Good luck!
The {competition_name} Team""",  # noqa (79char)
        ############ Readablity spacing ############
        "deletion_notification_body": """
This is a notification that the following {competition_name} account associated with this
email address has been deleted:

\t{username}

Due to the following reason:

\t{delete_reason}

The {competition_name} Team""",  # noqa (79char)
    },
    # CAPTCHA
    "captcha": {
        "enable_captcha": False,
        "captcha_url": "https://www.google.com/recaptcha/api/siteverify",
        "reCAPTCHA_public_key": "",
        "reCAPTCHA_private_key": "",
    },
    # SHELL SERVERS
    "shell_servers": {
        "enable_sharding": False,
        "default_stepping": 5000,
        "steps": [7500, 12500, 17500],
        "limit_added_range": False,
    },
    # MINIGAME TOKEN VALUES
    "minigame": {
        "secret": "foo",
        "token_values": {
            "a1": 10,
            "a2": 20,
            "a3": 30,
            "b1": 15,
            "b2": 30,
            "b3": 45,
            "c3": 20,
        },
    },
    # RATE LIMITING
    "enable_rate_limiting": True,
    # GROUP LIMIT
    "group_limit": 20,
}


def get_settings():
    """Retrieve settings from the database."""
    db = api.db.get_conn()
    settings = db.settings.find_one({}, {"_id": 0})
    if settings is None:
        db.settings.insert(default_settings.copy())
        return default_settings
    return settings


def merge_new_settings():
    """Add any new default_settings into the database."""

    def merge(a, b):
        """Merge new keys from nested dict a into b."""
        out = deepcopy(b)
        for k, v in a.items():
            if k not in out:
                out[k] = v
            elif isinstance(v, dict):
                out[k] = merge(v, out[k])
        return out

    db_settings = get_settings()
    merged = merge(default_settings, db_settings)
    db = api.db.get_conn()
    db.settings.find_one_and_update({}, {"$set": merged})


def change_settings(changes):
    """
    Update settings in the database.

    Raises:
        PicoException: if an updated key did not previously exist in settings,
                       or the updated value is of a different type

    """
    settings = get_settings()

    # @TODO validate incoming settings at the request level
    def check_keys(real, changed):
        keys = list(changed.keys())
        for key in keys:
            if key not in real:
                raise PicoException(
                    "Cannot update setting for '{}'".format(key)
                    + " (setting not found)",
                    status_code=400,
                )
            elif type(real[key]) != type(changed[key]):  # noqa:E721
                raise PicoException(
                    "Cannot update setting for '{}'".format(key) + " (incorrect type)",
                    status_code=400,
                )
            elif isinstance(real[key], dict):
                check_keys(real[key], changed[key])
                # change the key so mongo $set works correctly
                for key2 in changed[key]:
                    changed["{}.{}".format(key, key2)] = changed[key][key2]
                changed.pop(key)

    check_keys(settings, changes)
    db = api.db.get_conn()
    db.settings.find_one_and_update({}, {"$set": changes})


def check_competition_active():
    """Check whether the competition is currently running."""
    settings = get_settings()

    return (
        settings["start_time"].timestamp()
        < datetime.datetime.utcnow().timestamp()
        < settings["end_time"].timestamp()
    )


def block_before_competition(f):
    """
    Wrap routing functions that are blocked prior to the competition.

    Admins can bypass.
    """

    @wraps(f)
    def wrapper(*args, **kwargs):
        if api.user.is_logged_in() and api.user.get_user().get("admin", False):
            return f(*args, **kwargs)
        elif (
            datetime.datetime.utcnow().timestamp()
            <= get_settings()["start_time"].timestamp()
        ):
            raise PicoException("The competition has not begun yet!", 422)
        return f(*args, **kwargs)

    return wrapper


def block_after_competition(f):
    """
    Wrap routing functions that are blocked after the competition.

    Admins can bypass.
    """

    @wraps(f)
    def wrapper(*args, **kwargs):
        if api.user.is_logged_in() and api.user.get_user().get("admin", False):
            return f(*args, **kwargs)
        elif (
            datetime.datetime.utcnow().timestamp()
            >= get_settings()["end_time"].timestamp()
        ):
            raise PicoException("The competition has ended!", 422)
        return f(*args, **kwargs)

    return wrapper
