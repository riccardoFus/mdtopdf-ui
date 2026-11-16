.PHONY: install run test sample marp clean

install:
	./install.sh

run:
	./run.sh

test:
	.venv/bin/python -m pytest -q

sample:
	.venv/bin/python scripts/make_sample.py

marp:
	.venv/bin/python scripts/make_marp_sample.py

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache
