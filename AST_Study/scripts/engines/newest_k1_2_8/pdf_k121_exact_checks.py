"""Same-request elementary verification for retained technical claims.

Detect source syntax, never course names or specific example answers. The model
keeps all existing selection/evidence contracts and decides uncertainty normally.
"""
import re
VERSION='elementary-source-verification-v5'
RULES='''\nEXACT LOCAL TECHNICAL VERIFICATION (same response, existing sourceSetup fields):
Before teaching a retained symbolic transformation, check its smallest decisive
step independently of the printed result. For a power integral, verify that the
exponent increments and coefficient are consistent; differentiate a retained
antiderivative back to its integrand. Record that short decisive verification in
sourceSetup, not a repeated transcript. A printed answer is evidence of what was
printed, not proof of mathematical correctness. Only correct a source error when
an exact local identity independently establishes it. Do not invent a source
conflict from an uncertain mental calculation. A routine worked answer that adds
no new learning may be omitted while preserving its correct general method.
For a diagram-based integral, copy the decisive printed factor into sourceQuotes
and define the variable by its role in that factor. If the source writes
work = force × x, explain x as the layer's travel distance to its destination.
That definition suffices; do not add a separate axis origin or direction inferred
from the drawing. In boundaryChecks use the printed expression: the travel
distance must be zero at the destination, so no endpoint with a nonzero distance
may be called the destination. The physical region being integrated supplies the
integration limits; the destination supplies a separate distance reference.
Keep the printed setup when a faint diagram does not establish an alternative.
A guessed coordinate convention cannot justify replacing a printed factor.
For supplied executable code, compare each actual operation with its allocation,
type, lifetime and branch conditions. If your general rule makes an actual source
line invalid, name that exact operation/branch and its consequence in MAIN; a
correct generic rule elsewhere does not neutralize a contradictory worked line.
Keep the printed source identifiable. If presenting corrected code, explicitly
label it as a correction instead of attributing it verbatim to the PDF. Do not
add a caution to valid code. This is verification inside this SAME request, not
an extra review call or a requirement to solve routine exercises.\n'''
def kinds(blocks):
 text='\n'.join(str(b.get('text')or'')for b in blocks)
 symbolic=bool(re.search(r'[∫∑∏∂]|\\(?:int|sum|prod|frac)\b|\b(?:sin|cos|tan|sec|csc|cot)\b',text))
 lifetime=bool(re.search(r'\bdelete\s*(?:\[\s*\])?\s*[A-Za-z_]\w*|\bnew\s+\w+\s*\[|\b(?:malloc|calloc|realloc|free)\s*\(',text))
 return symbolic,lifetime

MATH_SELECTION='\nSYMBOLIC METHOD VS ROUTINE ANSWER: For a routine worked computation, teach the\nidentity, why the substitution applies, its differential and any changed bounds,\nand the resulting symbolic setup. Stop there unless the worked RESULT itself\nteaches a new principle or indispensable condition. A changed number, fractional\npower or another direct use of the same power rule does not by itself justify\nprinting the worked answer. Keep general formulas, actual derivations of a new\nlaw, source-taught domain conditions, proofs and algorithms: those are not\noptional routine arithmetic. Never omit the principle merely to omit its example.\nIf a result is indispensable, verify the FINAL LEARNER expression after every\nsubstitution back to the original variable as well as any repeated easy version.\nF(u) -> F(g(x)) preserves its coefficients and exponents exactly. A check in\nsourceSetup is insufficient if the final expression differs. Do not revert to an\nincompatible printed final line after a correct internal derivation. If omitting\na routine result, no source-error lecture or caution is needed; teach the correct\nmethod and retain normal source accounting. Do not add invented calculations.\n'

GRAPH_RULES="\nNUMERICAL PLOT SELECTION: For plots with numerical axes, teach the axis meanings,\ntrend/comparison, mechanism and lesson-relevant conditions. An arbitrary\nillustrative coordinate or equilibrium amount is not required merely because it\ncan be read from the plot. Retain a number only when that quantity, threshold,\nscale, quantitative result or source argument is itself needed for the lesson.\nIf retained, check the EXACT printed axis/caption unit and scale; never substitute\na familiar textbook unit or convert the number implicitly. Do not use external\nknowledge to rename a printed unit. Preserve necessary quantitative evidence,\nfull source-taught classifications, general equations and their valid domains.\nThis rule does not apply to graph-theory networks or require inventing numeric\naxes. An omitted incidental coordinate is not a reading limitation and needs no\nlearner-facing caution. Existing source coverage must still cite the plot's\nactual learning contribution.\n"
def chart(blocks):
    text='\n'.join(str(b.get('text')or'')for b in blocks)
    return bool(re.search(r'그래프|곡선|가로축|세로축|\b(?:axis|axes|curve|plot|graph)\b',text,re.I))
