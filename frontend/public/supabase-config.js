/**
 * lost2found • Supabase Client Configuration
 * Project URL: https://gdngcjfgajkjdjosgtlc.supabase.co
 */

(function () {
  const DEFAULT_URL = "https://gdngcjfgajkjdjosgtlc.supabase.co";
  let SUPABASE_URL = DEFAULT_URL;
  
  // Retrieve Anon Key from environment / localStorage / fallback
  let SUPABASE_ANON_KEY = 
    (typeof window !== "undefined" && window.__ENV__?.SUPABASE_ANON_KEY) ||
    (typeof localStorage !== "undefined" && localStorage.getItem("supabase_anon_key")) ||
    "";

  let supabaseClient = null;

  function initClient(url, key) {
    if (typeof supabase !== "undefined" && url && key && key !== "your_supabase_anon_key_here") {
      try {
        supabaseClient = supabase.createClient(url, key, {
          auth: {
            persistSession: true,
            autoRefreshToken: true,
            detectSessionInUrl: true
          }
        });
        SUPABASE_URL = url;
        SUPABASE_ANON_KEY = key;
        console.log("⚡ [lost2found] Supabase client connected to: " + url);
        return supabaseClient;
      } catch (e) {
        console.warn("⚠️ [lost2found] Supabase client initialization error:", e);
      }
    }
    return null;
  }

  // Attempt immediate init if key is present
  if (SUPABASE_ANON_KEY) {
    initClient(SUPABASE_URL, SUPABASE_ANON_KEY);
  }

  // Also query public config from backend if key is not yet in browser
  if (typeof fetch !== "undefined") {
    fetch('/api/config/public')
      .then(res => res.json())
      .then(cfg => {
        if (cfg && cfg.supabase_anon_key && cfg.supabase_anon_key !== "your_supabase_anon_key_here") {
          initClient(cfg.supabase_url || DEFAULT_URL, cfg.supabase_anon_key);
        }
      })
      .catch(() => {});
  }

  window.lost2foundSupabase = {
    url: SUPABASE_URL,
    get anonKey() { return SUPABASE_ANON_KEY; },
    getClient: function () {
      if (!supabaseClient) {
        const key = (typeof localStorage !== "undefined" && localStorage.getItem("supabase_anon_key")) || SUPABASE_ANON_KEY;
        if (key) {
          initClient(SUPABASE_URL, key);
        }
      }
      return supabaseClient;
    },
    setAnonKey: function (key) {
      if (key && typeof localStorage !== "undefined") {
        const cleaned = key.trim();
        localStorage.setItem("supabase_anon_key", cleaned);
        return initClient(SUPABASE_URL, cleaned);
      }
    },
    isConnected: function () {
      return Boolean(supabaseClient && SUPABASE_ANON_KEY && SUPABASE_ANON_KEY !== "your_supabase_anon_key_here");
    }
  };
})();
