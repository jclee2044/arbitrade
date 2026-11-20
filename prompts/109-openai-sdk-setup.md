Prepare this application's Python backend to use openai-agents==0.24.0
and openai==3.52.0. Perform the setup for me using CHECK, TAKE ACTION,
and VERIFY. Run the commands yourself and report their results.

CHECK
Read the project instructions and dependency files. Identify the Python
interpreter that starts this backend, its version, and its package environment.
Check the installed openai and openai-agents versions and run pip check.
Confirm that the requested versions are compatible with this environment.
Reuse the backend's existing environment. If both versions already match,
skip installation and proceed to VERIFY.

TAKE ACTION
If a change is needed, show the exact command, installation target, and
dependency files that would change. Ask for my approval, then run the approved
installation and record the two version pins in the project's dependency
file. Do not create a new environment, update unrelated packages, or remove
packages to resolve conflicts without approval. Report any conflict that
prevents this setup from working.

VERIFY
Using the same backend interpreter, import AsyncOpenAI from openai and
Agent, Runner, and function_tool from agents. Print the installed distribution
versions; they should be 3.52.0 and 0.24.0. Run pip check again and compare it
with the earlier result. Report any unresolved conflicts separately from a
successful import. Update the setup notes with the commands actually used
and the observed results. Identify whether the backend needs a restart.
