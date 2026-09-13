use aws_nitro_enclaves_nsm_api::{api::{Request, Response}, driver::{nsm_init, nsm_exit, nsm_process_request}};
use std::io::{Read, Write};
fn main() {
    let mut key = Vec::new();
    std::io::stdin().take(4096).read_to_end(&mut key).unwrap();
    assert!(!key.is_empty());
    let fd = nsm_init();
    assert!(fd >= 0, "NSM required");
    let response = nsm_process_request(fd, Request::Attestation {
        user_data: None, nonce: None, public_key: Some(serde_bytes::ByteBuf::from(key))
    });
    nsm_exit(fd);
    match response {
        Response::Attestation { document } => std::io::stdout().write_all(&document).unwrap(),
        _ => std::process::exit(1),
    }
}
