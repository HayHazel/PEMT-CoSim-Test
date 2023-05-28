/*
 * Copyright Xuyang Ma. All Rights Reserved.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

'use strict';

const { Gateway, Wallets } = require('fabric-network');
const path = require('path');
const { buildCCPOrg1, buildCCPOrg2, buildWallet, prettyJSONString} = require('../../test-application/javascript/AppUtil.js');
const fs = require('fs');
const {exit} = require('process');

const myChannel = 'mychannel';
const myChaincodeName = 'auction';

async function createWallet(ccp,wallet,user,name) {
	try {

		const gateway = new Gateway();
		await gateway.connect(ccp,
			{ wallet: wallet, identity: user, discovery: { enabled: true, asLocalhost: true } });

		const network = await gateway.getNetwork(myChannel);
		const contract = network.getContract(myChaincodeName);

               let statefulTxn = contract.createTransaction('CreateSharedWallet');
		console.log('\n--> create shared wallet');
		let result = await statefulTxn.submit(name);
		console.log('*** Result: Committed: ' + result);

		gateway.disconnect();
	} catch (error) {
		console.error(`******** FAILED to create shared wallet: ${error}`);
	}
}

async function main() {
	try {

		if (process.argv[2] === undefined || process.argv[3] === undefined || process.argv[4] === undefined ) {
			console.log('Usage: node createShareWallet.js org uesr walletname ');
			process.exit(1);
		}

		const org = process.argv[2];
		const user = process.argv[3];
		const name = process.argv[4];
		
		

		if (org === 'Org1' || org === 'org1') {
			const ccp = buildCCPOrg1();
			const walletPath = path.join(__dirname, 'wallet/org1');
			const wallet = await buildWallet(Wallets, walletPath);
			await createWallet(ccp,wallet,user,name);
		}
		else if (org === 'Org2' || org === 'org2') {
			const ccp = buildCCPOrg2();
			const walletPath = path.join(__dirname, 'wallet/org2');
			const wallet = await buildWallet(Wallets, walletPath);
			await createWallet(ccp,wallet,user,name);
		}  else {
			console.log('Usage: node createShareWallet.js org uesr walletname');
			console.log('Org must be Org1 or Org2');
		}
	} catch (error) {
		console.error(`******** FAILED to run the application: ${error}`);
	}
}


main();
