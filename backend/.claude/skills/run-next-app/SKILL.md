---
name: run-next-app
description: Run and interact with the Next.js application.
---

# Next.js Application

This skill allows you to run and interact with the **Next.js** application named **next-app**.

## Prerequisites
Make sure to install the following packages:
```bash
apt-get install -y nodejs npm
```

## Build
To build the application, run:
```bash
npm install
npm run build
```

## Run (Agent Path)
To launch the application, use the following command:
```bash
npm run start
```

## Gotchas
- Ensure all dependencies are installed correctly. Missing dependencies can prevent the app from starting.

## Troubleshooting
- If you encounter issues, verify that you have Node.js and npm installed and that you are using compatible versions.
