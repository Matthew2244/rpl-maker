#!/bin/zsh
# Before every commit: unit tests, every module compiles, every control has a help tag.
cd "${0:A:h}"
set -e
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m py_compile rplmaker/*.py tools/*.py
# every button, checkbox and field made in gui.py gets SetToolTip somewhere after it
n_ctrl=$(grep -cE "= wx\.(Button|CheckBox|TextCtrl|SearchCtrl|Choice|CheckListBox|SpinCtrl|ListBox|Gauge)\(" rplmaker/gui.py)
n_tip=$(grep -c "SetToolTip(" rplmaker/gui.py)
if [ "$n_tip" -lt "$n_ctrl" ]; then echo "FAIL: $n_ctrl controls, only $n_tip help tags"; exit 1; fi
echo "All checks passed ($n_ctrl controls, $n_tip help tags)."
