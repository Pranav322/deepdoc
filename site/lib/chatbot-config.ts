const envApiBaseUrl = process.env.NEXT_PUBLIC_CODEWIKI_CHATBOT_BASE_URL?.trim() ?? '';

export const chatbotConfig = {
  enabled: true,
  apiBaseUrl: envApiBaseUrl || 'http://127.0.0.1:8001',
};
