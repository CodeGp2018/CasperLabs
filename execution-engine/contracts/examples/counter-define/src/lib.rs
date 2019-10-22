#![no_std]

extern crate alloc;

extern crate contract_ffi;

use alloc::collections::BTreeMap;
use alloc::string::String;
use alloc::vec::Vec;

use contract_ffi::contract_api::TURef;
use contract_ffi::contract_api::{runtime, storage, Error as ApiError};
use contract_ffi::key::Key;
use contract_ffi::unwrap_or_revert::UnwrapOrRevert;

enum Arg {
    MethodName = 0,
}

#[repr(u16)]
enum Error {
    UnknownMethodName = 0,
}

impl Into<ApiError> for Error {
    fn into(self) -> ApiError {
        ApiError::User(self as u16)
    }
}

#[no_mangle]
pub extern "C" fn counter_ext() {
    let turef: TURef<i32> = runtime::get_key("count").unwrap().to_turef().unwrap();
    let method_name: String = runtime::get_arg(Arg::MethodName as u32)
        .unwrap_or_revert_with(ApiError::MissingArgument)
        .unwrap_or_revert_with(ApiError::InvalidArgument);
    match method_name.as_str() {
        "inc" => storage::add(turef, 1),
        "get" => {
            let result = storage::read(turef)
                .unwrap_or_revert_with(ApiError::Read)
                .unwrap_or_revert_with(ApiError::ValueNotFound);
            runtime::ret(result, Vec::new());
        }
        _ => runtime::revert(Error::UnknownMethodName),
    }
}

#[no_mangle]
pub extern "C" fn call() {
    let counter_local_key = storage::new_turef(0); //initialize counter

    //create map of references for stored contract
    let mut counter_urefs: BTreeMap<String, Key> = BTreeMap::new();
    let key_name = String::from("count");
    counter_urefs.insert(key_name, counter_local_key.into());

    let pointer = storage::store_function_at_hash("counter_ext", counter_urefs);
    runtime::put_key("counter", &pointer.into());
}