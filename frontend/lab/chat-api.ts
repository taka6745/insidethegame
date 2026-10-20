import { LabApi } from './api.ts';
import type { ChatProfile, ChatSession } from './types.ts';

export class ChatApi extends LabApi {
  profiles() { return this.request<{ profiles: ChatProfile[] }>('/chat/profiles'); }
  session(profileId: string) { return this.request<ChatSession>('/chat/sessions', { profile_id: profileId }); }
  history(token: string) { return this.request<ChatSession>(`/chat/${encodeURIComponent(token)}`); }
  ask(token: string, prompt: string, requestId: string) { return this.request(`/chat/${encodeURIComponent(token)}/messages`, { prompt, request_id: requestId }); }
  track(token: string, offerId: string) { return this.request(`/chat/${encodeURIComponent(token)}/offers/${encodeURIComponent(offerId)}/track`, {}); }
}
