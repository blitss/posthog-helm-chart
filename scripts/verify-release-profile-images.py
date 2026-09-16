#!/usr/bin/env python3
"""Project production image pins onto disposable CI values, not production config.

Usage: yq -o=json release.yaml | python3 scripts/verify-release-profile-images.py profile.json
The profile must also be JSON (yq -o=json can convert it).
"""

import json
import sys


def copy_images(source, target):
    for key, value in source.items():
        if key == "image":
            target[key] = value
            # CI pulls the same content directly rather than requiring production's
            # private pull-through cache credentials. Never substitute a digest.
            if isinstance(value, dict) and isinstance(value.get("repository"), str):
                value["repository"] = value["repository"].removeprefix("registry.streamloop.app/")
            elif isinstance(value, str):
                target[key] = value.removeprefix("registry.streamloop.app/")
        elif isinstance(value, dict):
            child = target.setdefault(key, {})
            if isinstance(child, dict):
                copy_images(value, child)
                if not child:
                    target.pop(key)


def main():
    with open(sys.argv[1]) as source:
        profile = json.load(source)
    release = json.load(sys.stdin)
    copy_images(profile["spec"]["values"], release["spec"]["values"])
    json.dump(release, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
