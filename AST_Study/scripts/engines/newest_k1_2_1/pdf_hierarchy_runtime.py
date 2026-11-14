"""Keep installed desktop workers on their shipped hierarchy until app rollout.

The desktop explicitly selects version 7 after its Java update is deployed.
Offline migration/research can opt in through the same environment variable.
"""
import os

if os.environ.get('SYNESIS_LOCAL_HIERARCHY') == '7':
    import pdf_study_hierarchy as hierarchy
else:
    import pdf_study_hierarchy_legacy as hierarchy
