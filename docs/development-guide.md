# Development Guide

This guide explains how the project should be developed during the hackathon foundation phase.

## Principles

- Keep each module independent.
- Use JavaScript ES modules.
- Follow async/await patterns.
- Keep functions small and readable.
- Use JSDoc for shared contracts.
- Avoid unnecessary dependencies.
- Do not commit credentials.

## Initial Setup

1. Clone the repository.
2. Run npm install.
3. Copy .env.example to .env when needed.
4. Use npm start to verify the app starts in initialization mode.

## Branching

The initial project foundation belongs on main. After the foundation is committed, each developer creates their own branch from main according to their assigned work.

## Integration Expectations

The Discord developer should not build database models. The MongoDB developer should not build Discord interactions. The LangChain developer should not build Discord handlers or Mongoose schemas.

## Shared Tooling

The shared contracts in src/shared/contracts.js and src/shared/validators.js are the communication layer used by all three implementations. These files establish the expected object schema and default validations for daily functionality.
