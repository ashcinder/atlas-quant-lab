import { Transaction } from 'ethers';
let input='';for await(const chunk of process.stdin){input+=chunk;if(input.length>150000)process.exit(2)}
try{const tx=Transaction.from(JSON.parse(input).raw_transaction);if(!tx.isSigned())throw Error();console.log(JSON.stringify({hash:tx.hash,from:tx.from,to:tx.to,value:tx.value.toString(),data:tx.data,chainId:tx.chainId.toString(),nonce:tx.nonce,gasLimit:tx.gasLimit.toString(),gasPrice:tx.gasPrice?.toString(),type:tx.type}));}catch{process.exit(2)}
