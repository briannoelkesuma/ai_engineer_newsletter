/**
 * Cloudflare Worker for YouTube WebSub (PubSubHubbub) Webhook
 */

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // 1. Manual Subscription Endpoint (GET /subscribe)
    if (url.pathname === '/subscribe' && request.method === 'GET') {
      try {
        await subscribeToWebSub(env);
        return new Response('Subscription request successfully sent to Google WebSub Hub!', {
          status: 200,
          headers: { 'Content-Type': 'text/plain' }
        });
      } catch (err) {
        return new Response(`Subscription failed: ${err.message}`, {
          status: 500,
          headers: { 'Content-Type': 'text/plain' }
        });
      }
    }

    // 2. WebSub Challenge Verification (GET /)
    if (request.method === 'GET') {
      const hubMode = url.searchParams.get('hub.mode');
      const hubTopic = url.searchParams.get('hub.topic');
      const hubChallenge = url.searchParams.get('hub.challenge');
      const hubLease = url.searchParams.get('hub.lease_seconds');

      console.log(`Received WebSub challenge request: mode=${hubMode}, topic=${hubTopic}`);

      if (hubMode === 'subscribe' || hubMode === 'unsubscribe') {
        // Optional: Verify topic matches our target channel feed
        const expectedTopic = `channel_id=${env.CHANNEL_ID}`;
        if (hubTopic && hubTopic.includes(expectedTopic)) {
          console.log(`Challenge verified! Reponding with challenge: ${hubChallenge}`);
          return new Response(hubChallenge, {
            status: 200,
            headers: { 'Content-Type': 'text/plain' }
          });
        } else {
          console.warn(`Challenge rejected: topic does not match expected channel ID (${env.CHANNEL_ID}).`);
          return new Response('Forbidden: Topic mismatch', { status: 403 });
        }
      }

      return new Response('Hello. This is the YouTube WebSub webhook worker. Visit /subscribe to renew subscription.', {
        status: 200,
        headers: { 'Content-Type': 'text/plain' }
      });
    }

    // 3. Webhook Event Notification (POST /)
    if (request.method === 'POST') {
      const bodyText = await request.text();
      console.log('Received WebSub POST notification.');

      // Verify signature if WEBHOOK_SECRET is set
      const signatureHeader = request.headers.get('x-hub-signature');
      if (env.WEBHOOK_SECRET && signatureHeader) {
        const isSignatureValid = await verifySignature(bodyText, signatureHeader, env.WEBHOOK_SECRET);
        if (!isSignatureValid) {
          console.error('Signature verification failed.');
          return new Response('Invalid signature', { status: 403 });
        }
        console.log('Signature verified successfully.');
      }

      // Parse XML payload using regex (safe & fast in Workers)
      const videoIdMatch = bodyText.match(/<yt:videoId>([^<]+)<\/yt:videoId>/);
      const titleMatch = bodyText.match(/<title>([^<]+)<\/title>/);
      const channelIdMatch = bodyText.match(/<yt:channelId>([^<]+)<\/yt:channelId>/);

      if (!videoIdMatch) {
        console.warn('No video ID found in payload. Ignoring.');
        return new Response('No video ID found', { status: 200 }); // Return 200 so Hub doesn't retry
      }

      const videoId = videoIdMatch[1];
      const title = titleMatch ? decodeXmlEntities(titleMatch[1]) : 'Unknown Title';
      const channelId = channelIdMatch ? channelIdMatch[1] : '';

      console.log(`Extracted video: ${title} (${videoId}) for channel: ${channelId}`);

      // Verify channel matches config
      if (channelId && channelId !== env.CHANNEL_ID) {
        console.warn(`Notification is for channel ${channelId}, expected ${env.CHANNEL_ID}. Ignoring.`);
        return new Response('Channel mismatch', { status: 200 });
      }

      // Insert into Supabase with 'ignore-duplicates' to check if it's new
      const isNewVideo = await insertVideoToSupabase(videoId, title, env);

      if (isNewVideo) {
        console.log(`New video detected! Triggering GitHub Action workflow...`);
        await triggerGitHubAction(videoId, title, env);
      } else {
        console.log(`Video ${videoId} already exists in database. Skipping pipeline trigger.`);
      }

      return new Response('Notification processed', { status: 200 });
    }

    return new Response('Method not allowed', { status: 405 });
  },

  // 4. Daily Cron Trigger for Subscription Renewal
  async scheduled(event, env, ctx) {
    console.log('Cron trigger running: Automatically renewing YouTube WebSub subscription...');
    try {
      await subscribeToWebSub(env);
      console.log('Subscription renewal request sent successfully!');
    } catch (err) {
      console.error(`Cron subscription renewal failed: ${err.message}`);
    }
  }
};

/**
 * Sends a subscription POST request to Google's WebSub Hub
 */
async function subscribeToWebSub(env) {
  if (!env.WORKER_URL) {
    throw new Error('WORKER_URL variable is not configured in wrangler.toml or environment.');
  }

  const topicUrl = `https://www.youtube.com/xml/feeds/videos.xml?channel_id=${env.CHANNEL_ID}`;
  const params = new URLSearchParams();
  params.append('hub.callback', env.WORKER_URL);
  params.append('hub.mode', 'subscribe');
  params.append('hub.topic', topicUrl);
  params.append('hub.lease_seconds', '432000'); // 5 days (432,000s)
  
  if (env.WEBHOOK_SECRET) {
    params.append('hub.secret', env.WEBHOOK_SECRET);
  }
  params.append('hub.verify', 'async');

  console.log(`Sending WebSub subscription request to hub for topic: ${topicUrl}`);
  
  const response = await fetch('https://pubsubhubbub.appspot.com/subscribe', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded'
    },
    body: params.toString()
  });

  if (!response.ok) {
    const errText = await response.text();
    throw new Error(`Hub response code ${response.status}: ${errText}`);
  }
}

/**
 * Verifies HMAC-SHA1 signature sent by YouTube
 */
async function verifySignature(bodyText, signatureHeader, secret) {
  try {
    const key = await crypto.subtle.importKey(
      'raw',
      new TextEncoder().encode(secret),
      { name: 'HMAC', hash: 'SHA-1' },
      false,
      ['verify']
    );

    const sigHex = signatureHeader.replace('sha1=', '');
    if (sigHex.length !== 40) return false;

    const sigBytes = new Uint8Array(sigHex.match(/.{1,2}/g).map(byte => parseInt(byte, 16)));
    
    return await crypto.subtle.verify(
      'HMAC',
      key,
      sigBytes,
      new TextEncoder().encode(bodyText)
    );
  } catch (err) {
    console.error('Error verifying HMAC signature:', err);
    return false;
  }
}

/**
 * Inserts the video into Supabase. Returns true if it was a new video, false if it already existed.
 */
async function insertVideoToSupabase(videoId, title, env) {
  const supabaseUrl = env.SUPABASE_URL;
  const supabaseKey = env.SUPABASE_KEY;

  if (!supabaseUrl || !supabaseKey) {
    console.error('Supabase credentials missing.');
    return false;
  }

  const url = `${supabaseUrl}/rest/v1/videos`;
  const body = {
    video_id: videoId,
    title: title,
    description: null,
    upload_date: null,
    status: 'pending'
  };

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'apikey': supabaseKey,
      'Authorization': `Bearer ${supabaseKey}`,
      'Content-Type': 'application/json',
      'Prefer': 'resolution=ignore-duplicates,return=representation'
    },
    body: JSON.stringify(body)
  });

  if (!response.ok) {
    const errText = await response.text();
    console.error(`Supabase insert failed: ${response.status} ${errText}`);
    return false;
  }

  const responseData = await response.json();
  // If return=representation is used, responseData contains the inserted rows.
  // If the array is empty, it means the row violated a unique constraint (duplicate) and was ignored.
  return Array.isArray(responseData) && responseData.length > 0;
}

/**
 * Triggers GitHub Actions workflow via repository dispatch API
 */
async function triggerGitHubAction(videoId, title, env) {
  const owner = env.GITHUB_OWNER;
  const repo = env.GITHUB_REPO;
  const token = env.GITHUB_TOKEN;

  if (!token) {
    console.error('GITHUB_TOKEN missing. Cannot trigger GitHub Action workflow.');
    return;
  }

  const url = `https://api.github.com/repos/${owner}/${repo}/dispatches`;
  const body = {
    event_type: 'new_video_uploaded',
    client_payload: {
      video_id: videoId,
      title: title
    }
  };

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Authorization': `token ${token}`,
      'Accept': 'application/vnd.github.v3+json',
      'User-Agent': 'CF-Worker-YouTube-WebSub',
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(body)
  });

  if (!response.ok) {
    const errText = await response.text();
    console.error(`GitHub dispatch failed: ${response.status} ${errText}`);
  } else {
    console.log('GitHub workflow dispatch triggered successfully.');
  }
}

/**
 * Decodes XML entities like &amp;, &lt;, &gt;, &quot;, &apos;
 */
function decodeXmlEntities(str) {
  return str
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'");
}
