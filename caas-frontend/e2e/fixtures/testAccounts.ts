import * as fs from 'fs';
import * as path from 'path';

const ACCOUNTS_FILE = path.join(__dirname, '..', '.test-accounts.json');

/**
 * Generates a unique test email address.
 * Convention: test_pw_<timestamp>@hopnshoppe.test
 */
export function createTestEmail(): string {
  return `test_pw_${Date.now()}@hopnshoppe.test`;
}

/**
 * Registers an email for cleanup in global-teardown.
 * Appends the email to .test-accounts.json so teardown can delete it.
 */
export function registerForCleanup(email: string): void {
  let emails: string[] = [];
  if (fs.existsSync(ACCOUNTS_FILE)) {
    emails = JSON.parse(fs.readFileSync(ACCOUNTS_FILE, 'utf8'));
  }
  if (!emails.includes(email)) {
    emails.push(email);
    fs.writeFileSync(ACCOUNTS_FILE, JSON.stringify(emails, null, 2));
  }
}

/**
 * Helper: signup a test user via API (bypassing the UI) and return their JWT.
 * Used in tests that need a pre-authenticated session without testing the signup UI.
 */
export async function apiSignupAndLogin(
  email: string,
  firstName: string,
  lastName: string,
  password: string
): Promise<string> {
  // Signup
  const signupRes = await fetch('http://localhost:5173/auth/signup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, firstName, lastName, password }),
  });
  if (!signupRes.ok && signupRes.status !== 409) {
    throw new Error(`Signup failed: ${signupRes.status}`);
  }

  // Login
  const loginRes = await fetch('http://localhost:5173/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: email, password }),
  });
  if (!loginRes.ok) {
    throw new Error(`Login failed: ${loginRes.status}`);
  }
  const { token } = await loginRes.json();
  return token;
}
