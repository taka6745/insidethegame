import { LabApi } from './api.js';

export class ChatApi extends LabApi {
  profiles() { return this.request('/chat/profiles'); }
  session(profileId) { return this.request('/chat/sessions', { profile_id: profileId }); }
  history(token) { return this.request(`/chat/${encodeURIComponent(token)}`); }
  ask(token, prompt, requestId) { return this.request(`/chat/${encodeURIComponent(token)}/messages`, { prompt, request_id: requestId }); }
  track(token, offerId) { return this.request(`/chat/${encodeURIComponent(token)}/offers/${encodeURIComponent(offerId)}/track`, {}); }
}
