package main

import "github.com/gin-gonic/gin"

func auth(c *gin.Context) {}
func audit(c *gin.Context) {}
func healthHandler(c *gin.Context) {}
func listUsers(c *gin.Context) {}
func createUser(c *gin.Context) {}

func main() {
    router := gin.New()
    api := router.Group("/api", auth)
    v1 := api.Group("/v1")
    admin := v1.Group("/admin", audit)

    router.GET("/health", healthHandler)
    admin.GET("/users", listUsers)
    admin.POST("/users", createUser)
}
