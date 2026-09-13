// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {IRiscZeroVerifier} from "../vendor/risc0/IRiscZeroVerifier.sol";

/// Proves exact journal bytes for one immutable Atlas guest. No administrator
/// can insert a result without calling the cryptographic verifier.
/// This registry does not parse strategy IDs or claim live exchange provenance.
contract AtlasReceiptRegistry {
    IRiscZeroVerifier public immutable verifier;
    bytes32 public immutable imageId;
    mapping(bytes32 => bool) public verifiedJournals;
    event JournalVerified(bytes32 indexed imageId, bytes32 indexed journalDigest, address indexed submitter);

    constructor(address verifier_, bytes32 imageId_) {
        require(verifier_.code.length > 0 && imageId_ != bytes32(0), "invalid configuration");
        verifier = IRiscZeroVerifier(verifier_);
        imageId = imageId_;
    }

    function submit(bytes calldata seal, bytes calldata journal) external {
        bytes32 digest = sha256(journal);
        require(!verifiedJournals[digest], "already verified");
        verifier.verify(seal, imageId, digest);
        verifiedJournals[digest] = true;
        emit JournalVerified(imageId, digest, msg.sender);
    }
}
