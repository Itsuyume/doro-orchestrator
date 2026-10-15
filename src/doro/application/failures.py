import re

from doro.domain.policy import SENSITIVE


def public_error(error: BaseException) -> str:
    text = str(error)
    for pattern in SENSITIVE:
        text = re.sub(pattern, "[redacted]", text)
    return text[:2000]
