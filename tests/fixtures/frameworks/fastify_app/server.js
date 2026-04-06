const fastify = require('fastify')()

async function apiRoutes(instance) {
  instance.get('/users', {
    preHandler: [auth, audit],
    schema: {
      body: { type: 'object' },
      response: { 200: { type: 'object' } }
    }
  }, listUsers)

  instance.route({
    method: 'POST',
    url: '/users',
    onRequest: [auth],
    preValidation: validateUser,
    schema: {
      body: { type: 'object' },
      response: { 201: { type: 'object' } }
    },
    handler: createUser
  })
}

fastify.register(apiRoutes, { prefix: '/api/v1' })
