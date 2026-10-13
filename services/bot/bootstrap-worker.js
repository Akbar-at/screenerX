// Used only to create the Worker before connecting Cloudflare's remote build.
export default {
  fetch() {
    return Response.json({status: 'deployment_pending', service: 'screenerx',
      message: 'The research container has not been deployed yet.'}, {status: 503});
  },
};
