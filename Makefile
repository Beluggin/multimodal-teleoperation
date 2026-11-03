# No hardware or API key needed for any of these.
.PHONY: test eval

test:
	@for d in tank_vision tank_tools tank_phone tank_speech; do \
		echo "== $$d"; \
		python3 -m unittest discover -s tests/$$d -p 'test_*.py' || exit 1; \
	done

eval:
	python3 eval/language_eval.py parser
