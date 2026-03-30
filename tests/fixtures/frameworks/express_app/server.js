const express = require('express')
const app = express()
const router = express.Router()
const adminRouter = express.Router()

router.route('/users').get(auth, listUsers).post(createUser)
adminRouter.get('/stats', requireAdmin, statsHandler)
router.use('/admin', adminRouter)
app.use('/api/v1', router)
