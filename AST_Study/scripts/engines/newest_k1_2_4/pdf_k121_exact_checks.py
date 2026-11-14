"""Same-request elementary verification for retained technical claims.

Detect source syntax, never course names or specific example answers. The model
keeps all existing selection/evidence contracts and decides uncertainty normally.
"""
import re
VERSION='elementary-source-verification-v3'
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
For supplied executable code, explain the actual shown operations in order. Track
each member after its latest write and distinguish the object written to, the value
or reference returned, and the operand that reads that result. State an explicitly
shown invalid operation with its exact condition. Do not analyze unshown inputs or
invent failure scenarios. A reference to an object observes its current members.
When an operation result feeds an enclosing expression, name the two expressions in
evaluation order and identify the exact returned value and consuming operand. Keep
this operational explanation in MAIN. Easy text may clarify a distinct term without
replaying the operations or introducing other inputs.
Keep the printed source identifiable. If presenting corrected code, explicitly
label it as a correction instead of attributing it verbatim to the PDF. Do not
add a caution to valid code. This is verification inside this SAME request, not
an extra review call or a requirement to solve routine exercises.\n'''
def kinds(blocks):
 text='\n'.join(str(b.get('text')or'')for b in blocks)
 symbolic=bool(re.search(r'[∫∑∏∂]|\\(?:int|sum|prod|frac)\b|\b(?:sin|cos|tan|sec|csc|cot)\b',text))
 lifetime=bool(re.search(r'\bdelete\s*(?:\[\s*\])?\s*[A-Za-z_]\w*|\bnew\s+\w+\s*\[|\b(?:malloc|calloc|realloc|free)\s*\(',text))
 return symbolic,lifetime

MATH_SELECTION='''
SYMBOLIC METHODS: A routine computation using a previously taught method adds no
learner text. For a genuinely new method, teach its identity, substitutions,
differential, bounds, and complete unevaluated setup. Keep general formulas,
derivations of new laws, domain conditions, proofs and algorithms. Every retained
transformation must agree with the original variable and assumptions in MAIN and
easyExplanation. F(u) -> F(g(x)) preserves coefficients and exponents exactly.
Use the source's variable convention together with the unevaluated setup.
For a spatial exercise, generalize the sizes in the printed factors and bounds
as one relation. State the coordinate origin/direction and verify the radius and
travel at both endpoints before writing the expression. A coordinate that equals
distance to the destination is zero at that destination. Identify the physical
interval occupied by the material. Keep one variable convention throughout.
'''

GRAPH_RULES="\nNUMERICAL PLOT SELECTION: For plots with numerical axes, teach the axis meanings,\ntrend/comparison, mechanism and lesson-relevant conditions. An arbitrary\nillustrative coordinate or equilibrium amount is not required merely because it\ncan be read from the plot. Retain a number only when that quantity, threshold,\nscale, quantitative result or source argument is itself needed for the lesson.\nIf retained, check the EXACT printed axis/caption unit and scale; never substitute\na familiar textbook unit or convert the number implicitly. Do not use external\nknowledge to rename a printed unit. Preserve necessary quantitative evidence,\nfull source-taught classifications, general equations and their valid domains.\nThis rule does not apply to graph-theory networks or require inventing numeric\naxes. An omitted incidental coordinate is not a reading limitation and needs no\nlearner-facing caution. Existing source coverage must still cite the plot's\nactual learning contribution.\n"
def chart(blocks):
    text='\n'.join(str(b.get('text')or'')for b in blocks)
    return bool(re.search(r'그래프|곡선|가로축|세로축|\b(?:axis|axes|curve|plot|graph)\b',text,re.I))
