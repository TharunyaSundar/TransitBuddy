import 'dotenv/config';

export const env = {
  nodeEnv: process.env.NODE_ENV || 'development',
  discordToken: process.env.DISCORD_TOKEN || '',
  discordClientId: process.env.DISCORD_CLIENT_ID || '',
  discordGuildId: process.env.DISCORD_GUILD_ID || '',
  mongodbUri: process.env.MONGODB_URI || '',
  mongodbDatabase: process.env.MONGODB_DATABASE || 'transit_buddy',
  llmProvider: process.env.LLM_PROVIDER || '',
  llmModel: process.env.LLM_MODEL || '',
  openAiApiKey: process.env.OPENAI_API_KEY || '',
  googleApiKey: process.env.GOOGLE_API_KEY || '',
  defaultTimezone: process.env.DEFAULT_TIMEZONE || 'America/Phoenix',
};

export function isConfigured(name) {
  return Boolean(env[name] && String(env[name]).trim() !== '');
}

export default env;
