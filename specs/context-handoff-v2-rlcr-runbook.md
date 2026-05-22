# Context Handoff V2 RLCR Runbook

## Default Model Strategy

- Humanize RLCR loop: `gpt-5.5:high`
- Final independent review only: `gpt-5.5:xhigh`
- Do not change global Codex config for this run.

## Start RLCR

Run from the repository root:

```powershell
& 'D:\install\Git\bin\bash.exe' 'C:\Users\Administrator\.cc-switch\skills\humanize\scripts\setup-rlcr-loop.sh' specs/context-handoff-v2-humanize-plan.md --codex-model gpt-5.5:high --base-branch main --full-review-round 3 --max 20 --skip-quiz
```

Then follow the generated `.humanize/rlcr/<timestamp>/round-*-prompt.md` instructions and always run the gate after each work round:

```powershell
& 'D:\install\Git\bin\bash.exe' 'C:\Users\Administrator\.cc-switch\skills\humanize\scripts\rlcr-stop-gate.sh'
```

## Final Xhigh Review

After Humanize RLCR has passed and the working tree is ready for final review, run:

```powershell
codex review --base main -c model=gpt-5.5 -c review_model=gpt-5.5 -c model_reasoning_effort=xhigh
```

Fix any reported issues, then rerun the same final review once.
