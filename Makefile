include config.env
export
.RECIPEPREFIX := >
PY=sudo -E venv/bin/python
CTL=$(PY) tools/lab.py

.PHONY: doctor build up down test demo experiments tables capture evidence check package hostaccess scaffold

doctor:
> sudo -E python3 tools/lab.py doctor
build:
> python3 tools/lab.py build
up:
> $(CTL) up
down:
> $(CTL) down
test:
> $(PY) tools/stagetests.py all
demo:
> $(CTL) demo
experiments:
> $(PY) tools/orchestrate.py all
tables:
> venv/bin/python tools/make_tables.py
capture:
> $(CTL) capture
evidence:
> $(CTL) evidence
hostaccess:
> $(CTL) hostaccess
scaffold:
> python3 tools/lab.py scaffold
check:
> venv/bin/python tools/lab.py check
package:
> $(PY) tools/lab.py package
