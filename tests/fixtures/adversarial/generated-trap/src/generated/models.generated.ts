// @generated DO NOT EDIT
// This file is auto-generated. DeepDoc must detect the @generated comment
// AND the /generated/ path segment AND the .generated.ts suffix
// and classify it as "generated" with source_trust=0.0

export interface GeneratedUser {
  id: number;
  name: string;
  email: string;
  roles: string[];
}

export interface GeneratedSession {
  id: string;
  userId: number;
  token: string;
  expiresAt: string;
}

export class UserRepository {
  findById(id: number): GeneratedUser {
    return { id, name: "Generated", email: `user${id}@test.com`, roles: ["user"] };
  }
}