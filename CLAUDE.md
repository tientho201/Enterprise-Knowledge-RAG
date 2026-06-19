# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Commands

### Development Commands
- **Building the Project**: Use `npm run build` to compile the frontend assets.
- **Linting the Code**: Run `npm run lint` to check for linting errors in the codebase.
- **Running Tests**: Execute `npm test` to run all tests in the repository. For a single test, you can specify the test file: `npm test -- <test-file-name>`.

## Code Architecture

The codebase consists of a backend written in Python and a frontend built with React and TypeScript. Here’s an overview of the structure:

### Backend
- Organized into a modular structure with clear separation between services, agents, and database interactions. 
- The main entry point is `backend/app/main.py`, which initializes the application.
- Services handle business logic, and agents manage specific tasks, such as `chat_service` and `web_search`.
- Tests are located in `backend/app/tests`, which include integration and unit tests to ensure code reliability.

### Frontend
- The frontend is built using React with TypeScript, where components are structured within the `frontend/components` directory.
- Important configurations are specified in `frontend/next.config.ts`.
- APIs are handled through defined routes to ensure a clean interaction between frontend and backend systems.

## Important Files
- Look for configuration and runtime settings in `backend/app/core/config.py`.
- Integration with external services, like document storage, is abstracted through connectors found in `backend/app/connectors`.

There are no specific cursor rules or Copilot instructions found for this repository. This CLAUDE.md serves as an initial framework and should be updated as the project evolves.