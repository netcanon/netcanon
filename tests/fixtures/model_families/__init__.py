"""Synthetic model families for tests -- never shipped.

Real families live under ``netcanon/definitions/library/model_families/``
and the tests load them from there.  This package holds the one that
exists only so a code path has something to run on.

``markup_family.yaml`` is a family an operator might have written for
their own device (the application reads ``model_families/`` under its
definitions directory beside the shipped ones), in which every string a
person can author is markup that would run a script if a page ever read
it as HTML.  Its one model's panel is graded ``inferred``, which no
shipped family is, so it is also what drives the rename modal's amber
"port names NOT verified" note for a family model.  Copy the file into
the test's definitions directory before the app loads it.
"""

from __future__ import annotations

from pathlib import Path

#: The synthetic family whose every authored string is markup.
MARKUP_FAMILY_YAML = Path(__file__).with_name("markup_family.yaml")

#: Its key, as the registry and the API spell it.
MARKUP_FAMILY_KEY = "aruba_aoss/FIXTURE-MARKUP"

#: Its one model, as the rename modal's model lists name it.
MARKUP_FAMILY_MODEL_OPTION = "fam:FIXTURE-MARKUP:MARKUP-8"

#: The page variable each of its strings would push to if it ran.
MARKUP_RAN = "__markup_ran"
