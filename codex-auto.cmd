@echo off
setlocal

rem Project-local Codex launcher for E:\statistics-toolbox-You.
rem Uses codex.cmd instead of codex.ps1 so Windows PowerShell execution policy
rem does not block the npm shim.

codex.cmd --dangerously-bypass-approvals-and-sandbox -C "%~dp0.." %*
