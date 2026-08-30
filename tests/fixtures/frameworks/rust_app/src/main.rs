use actix_web::{get, post, web, App, HttpResponse, HttpServer, Responder};
use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize)]
pub struct User {
    pub id: u64,
    pub name: String,
    pub email: String,
}

#[get("/api/users")]
pub async fn list_users() -> impl Responder {
    let users = vec![
        User { id: 1, name: "Alice".into(), email: "alice@example.com".into() },
    ];
    HttpResponse::Ok().json(users)
}

#[post("/api/users")]
pub async fn create_user(user: web::Json<User>) -> impl Responder {
    HttpResponse::Created().json(user.into_inner())
}

#[actix_web::main]
async fn main() -> std::io::Result<()> {
    HttpServer::new(|| {
        App::new()
            .service(list_users)
            .service(create_user)
    })
    .bind("127.0.0.1:8080")?
    .run()
    .await
}