# Architecture Overview

Transit Buddy is designed as a small, modular system with three independently owned components that come together through shared contracts.

## Core Design

The project is intentionally split into three implementation domains:

1. Discord integration for user interaction.
2. MongoDB persistence and validation.
3. LangChain agent reasoning with skill-driven behavior.

Each domain owns its own directory and is responsible for implementing the parts described in the shared service contracts.

## Boundaries

- The Discord layer does not directly manage Mongoose models.
- The database layer does not implement Discord handlers.
- The agent layer does not directly manage Discord commands or bot state.

Shared contracts are the only integration boundary between them.

## Startup Behavior

During the initial project foundation phase, the application can start without external infrastructure. This ensures that the project remains runnable even before credentials or live services are configured.

## Future Integration

Once the branches become active, each developer will implement their own module in a way that respects the documented APIs and data models.
