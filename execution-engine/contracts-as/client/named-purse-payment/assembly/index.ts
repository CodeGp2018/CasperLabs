import * as CL from "../../../../contract-as/assembly";
import {getKey} from "../../../../contract-as/assembly";
import {Error, ErrorCode} from "../../../../contract-as/assembly/error";
import {CLValue} from "../../../../contract-as/assembly/clvalue";
import {U512} from "../../../../contract-as/assembly/bignum";
import {fromBytesString} from "../../../../contract-as/assembly/bytesrepr";
import {URef} from "../../../../contract-as/assembly/uref";
import {KeyVariant} from "../../../../contract-as/assembly/key";
import {transferFromPurseToPurse} from "../../../../contract-as/assembly/purse";
import {RuntimeArgs} from "../../../../contract-as/assembly/runtime_args";
import {Pair} from "../../../../contract-as/assembly/pair";

const GET_PAYMENT_PURSE = "get_payment_purse";
const SET_REFUND_PURSE= "set_refund_purse";
const ARG_AMOUNT = "amount";
const ARG_PURSE = "purse";
const ARG_PURSE_NAME = "purse_name";

function getPurseURef(): URef | null{
  let purseNameBytes = CL.getNamedArg(ARG_PURSE_NAME);

  let purseName = fromBytesString(purseNameBytes);
  if (purseName.hasError()) {
    Error.fromErrorCode(ErrorCode.InvalidArgument);
    return null;
  }

  let purseKey = getKey(purseName.value);
  if (purseKey === null) {
    Error.fromErrorCode(ErrorCode.InvalidArgument);
    return null;
  }

  if (purseKey.variant != KeyVariant.UREF_ID) {
    Error.fromErrorCode(ErrorCode.UnexpectedKeyVariant);
    return null;
  }

  let purse = <URef>purseKey.uref;

  return purse;
}

export function call(): void {
  let maybePurseURef = getPurseURef();
  if (maybePurseURef === null) {
    Error.fromErrorCode(ErrorCode.InvalidArgument).revert();
    return;
  }

  let purseURef = <URef>maybePurseURef;

  let amountBytes = CL.getNamedArg(ARG_AMOUNT);
  let amountResult = U512.fromBytes(amountBytes);
  if (amountResult.hasError()) {
    Error.fromErrorCode(ErrorCode.InvalidArgument).revert();
    return;
  }
  let amount = amountResult.value;

  let proofOfStake = CL.getSystemContract(CL.SystemContract.ProofOfStake);

  // Get Payment Purse
  let paymentPurseOutput = CL.callContract(proofOfStake, GET_PAYMENT_PURSE, new RuntimeArgs());

  let paymentPurseResult = URef.fromBytes(paymentPurseOutput);
  if (paymentPurseResult.hasError()) {
    Error.fromErrorCode(ErrorCode.InvalidPurse).revert();
    return;
  }
  let paymentPurse = paymentPurseResult.value;

  // Set Refund Purse
  let runtimeArgs = RuntimeArgs.fromArray([
    new Pair(ARG_PURSE, CLValue.fromURef(purseURef)),
  ]);
  CL.callContract(proofOfStake, SET_REFUND_PURSE, runtimeArgs);

  let ret = transferFromPurseToPurse(
    purseURef,
    paymentPurse,
    amount,
  );
  if (ret > 0) {
    Error.fromErrorCode(ErrorCode.Transfer).revert();
    return;
  }
}
