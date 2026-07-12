import { exec } from 'child_process';

// Function to start the Next.js app
function startNextApp() {
    exec('npm run dev', {cwd: 'frontend'}, (error, stdout, stderr) => {
      if (error) {
          console.error(`Error starting app: ${error.message}`);
          return;
      }
      if (stderr) {
          console.error(`stderr: ${stderr}`);
          return;
      }
      console.log(`stdout: ${stdout}`);
    });
}

// Start the application
startNextApp();
