# Development Guide

This guide explains how the project should be developed during the hackathon foundation phase.

## Principles

- Keep each module independent.
- Use Python 3.11+ with type hints.
- Follow PEP 8; use async/await for I/O (discord.py is async).
- Keep functions small and readable.
- Use Pydantic models and docstrings for shared contracts.
- Avoid unnecessary dependencies.
- Do not commit credentials.

## Initial Setup

1. Clone the repository.
2. Create a virtualenv and run `pip install -r requirements.txt`.
3. Copy .env.example to .env when needed.
4. Use `python -m transit_buddy` to verify the app starts in initialization mode.

## Branching

The initial project foundation belongs on main. After the foundation is committed, each developer creates their own branch from main according to their assigned work.

## Integration Expectations

The Discord developer should not build database models. The MongoDB developer should not build Discord interactions. The LangChain developer should not build Discord handlers or database models.

## Shared Tooling

The shared contracts in transit_buddy/shared/contracts.py and transit_buddy/shared/validators.py are the communication layer used by all three implementations. These files establish the expected object schema and default validations for daily functionality.
