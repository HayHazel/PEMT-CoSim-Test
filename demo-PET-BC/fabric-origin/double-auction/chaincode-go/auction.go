/*
 * SPDX-License-Identifier: Apache-2.0
 */

package main

import (
	"crypto/sha1"
	"encoding/hex"
	"sort"
	"strconv"
	"strings"

	flogging "github.com/Hnampk/fabric-flogging"
)

type BuyerBid struct {
	Address    string  `json:"address"`
	Prices     float64 `json:"price"`
	Quantities int     `json:"quantity"`
}

type SellerBid struct {
	Address    string  `json:"address"`
	Prices     float64 `json:"price"`
	Quantities int     `json:"quantity"`
}

type Auction struct {
	Closed     bool        `json:"closed"`
	Buyers     []BuyerBid  `json:"buyersBid"`
	Sellers    []SellerBid `json:"sellersBid"`
	BuyersPay  [20]float64 `json:"buyersPay"`
	SellersPay [20]float64 `json:"sellersPay"`
}

type Accounts struct {
	Address []string  `json:"address"`
	Balance []float64 `json:"balance"`
}

// user wallet
type Accounts1 struct {
	Name    string  `json:"name"`
	Address string  `json:"address"`
	Balance float64 `json:"balance"`
}

//shared wallet account
type SW struct {
	Seller_Address string  `json:"seller_address"`
	Buyer_Address  string  `json:"buyer_address"`
	Seller_Balance float64 `json:"seller_balance"`
	Buyer_Balance  float64 `json:"buyer_balance"`
	Flag           int     `json:"flag"`
}

type SharedWallet struct {
	Seller_Balance float64 `json:"seller_balance"`
	Buyer_Balance  float64 `json:"buyer_balance"`
}

type SM struct {
	Transaction_Time  string `json:"transaction_time"`
	Transaction_Power string `json:"transaction_power"`
}

type SMarray struct {
	SMS []SM `json:"sm"`
}

type BySellerPrice []SellerBid

type Htlc struct {
	Id     string  `json:"Id"`
	Sender string  `json:"sender"`
	Amount float64 `json:"amount"`

	// Get ID of submitting client identity `json:"pre_image"`
	HashValue string `json:"hash_value"`
	State     int    `json:"state"`
}

type event struct {
	From  string  `json:"from"`
	To    string  `json:"to"`
	Value float64 `json:"value"`
}

func (a BySellerPrice) Len() int           { return len(a) }
func (a BySellerPrice) Less(i, j int) bool { return a[i].Prices < a[j].Prices }
func (a BySellerPrice) Swap(i, j int)      { a[i], a[j] = a[j], a[i] }

type ByBuyerPrice []BuyerBid

func (a ByBuyerPrice) Len() int           { return len(a) }
func (a ByBuyerPrice) Less(i, j int) bool { return a[i].Prices < a[j].Prices }
func (a ByBuyerPrice) Swap(i, j int)      { a[i], a[j] = a[j], a[i] }

func AddBid(addr string, prices []float64, quantities []int, auction *Auction) {
	if len(prices) == 1 {
		b := new(BuyerBid)
		b.Address = addr
		b.Prices = prices[0]
		b.Quantities = quantities[0]
		auction.Buyers = append(auction.Buyers, *b)
		sort.Sort(sort.Reverse(ByBuyerPrice(auction.Buyers)))
	} else {
		b := new(SellerBid)
		b.Address = addr
		b.Prices = prices[0]
		b.Quantities = quantities[0]
		auction.Sellers = append(auction.Sellers, *b)
		sort.Sort(BySellerPrice(auction.Sellers))
	}
}

func StoreSmData(t string, amount string, smArray *SMarray) {
	smData := new(SM)
	smData.Transaction_Time = t
	smData.Transaction_Power = amount
	smArray.SMS = append(smArray.SMS, *smData)
}

func Allocate(buyers []BuyerBid, sellers []SellerBid) [100]bool {
	buyersNum := len(buyers)
	winners := [100]bool{}
	for i := 0; i < buyersNum; i++ {
		winners[i] = true
	}
	return winners
}

func DeterminePayment(buyers []BuyerBid, sellers []SellerBid) ([]float64, []float64, int, float64) {
	var logger = flogging.MustGetLogger("fabric-double-auction")
	var sellerPricesList []float64
	var buyerPricesList []float64
	for _, buyer := range buyers {
		for i := 0; i < buyer.Quantities; i++ {
			buyerPricesList = append(buyerPricesList, buyer.Prices)
		}
	}
	for _, seller := range sellers {
		for i := 0; i < seller.Quantities; i++ {
			sellerPricesList = append(sellerPricesList, seller.Prices)
		}
	}
	if buyerPricesList[0] < sellerPricesList[0] {
		logger.Error("cannot make double auction")
	}
	if buyerPricesList[0] > sellerPricesList[len(sellerPricesList)-1] {
		logger.Error("max buyer bids > max seller bids, cannot make double auction, buyer bids too high")
	}
	var clearedPrice float64
	var clearedUnits int
	for i := 0; i < Min(len(buyerPricesList), len(sellerPricesList)); i++ {
		// figure 7
		if (buyers[0].Quantities > len(sellerPricesList)) && buyerPricesList[0] > sellerPricesList[len(sellerPricesList)-1] {
			clearedUnits = len(sellerPricesList)
			clearedPrice = buyerPricesList[0]
			break
		}
		// figure 12
		if (buyers[0].Quantities == len(sellerPricesList)) && buyerPricesList[0] > sellerPricesList[len(sellerPricesList)-1] {
			clearedUnits = len(sellerPricesList)
			clearedPrice = sellerPricesList[len(sellerPricesList)-1]
			break
		}
		//figure 8
		if buyerPricesList[0] < sellerPricesList[0] {
			clearedUnits = 0
			clearedPrice = (buyerPricesList[0] + sellerPricesList[0]) / 2
			break
		}
		if (buyerPricesList[i] - sellerPricesList[i]) < 0 {
			clearedUnits = i
			// this switch presents the double auction figure on:
			// http://gridlab-d.shoutwiki.com/wiki/Market_Auction
			switch {
			//figure 1
			case sellerPricesList[i] == (sellerPricesList[i-1]):
				clearedPrice = sellerPricesList[i]
				break
			//figure 4
			case (sellerPricesList[i-1] > buyerPricesList[i]) && (buyerPricesList[i-1] > sellerPricesList[i]):
				clearedPrice = sellerPricesList[i]
				break
			//figure 2
			case buyerPricesList[i] == (buyerPricesList[i-1]):
				clearedPrice = buyerPricesList[i]
				break
			//figure 5
			case buyerPricesList[i-1] > (sellerPricesList[i]) && sellerPricesList[i-1] < (buyerPricesList[i]):
				clearedPrice = buyerPricesList[i]
				break
			//figure 3
			case (buyerPricesList[i-1] < (sellerPricesList[i])) && (buyerPricesList[i] < (sellerPricesList[i-1])):
				clearedPrice = (buyerPricesList[i-1] + sellerPricesList[i-1]) / 2
				break
			//figure 6, 9, 10
			case sellerPricesList[i-1] == buyerPricesList[i-1]:
				clearedPrice = sellerPricesList[i-1]
				break
			default:
				logger.Error("error case")
			}
			break
		}
		// special case, if last few bids for sellers or buyers are equal, without this code below would cause unis and prices = 0
		if (buyerPricesList[i]-sellerPricesList[i]) == 0 && (i == Min(len(buyerPricesList), len(sellerPricesList))-1) {
			clearedUnits = Min(len(buyerPricesList), len(sellerPricesList))
			clearedPrice = buyerPricesList[i]
		}
		if i == Min(len(buyerPricesList), len(sellerPricesList))-1 {
			clearedUnits = i + 1
			clearedPrice = sellerPricesList[i]
		}
	}
	logger.Error("-----------------------------------------")
	logger.Error("clearedUnits", clearedUnits)
	logger.Error("-----------------------------------------")
	logger.Error("-----------------------------------------")
	logger.Error("clearedPrice", clearedPrice)
	logger.Error("-----------------------------------------")
	//buyersNum := len(buyers)
	//sellersNum := len(sellers)
	buyersPay := [20]float64{}
	sellersPay := [20]float64{}

	var exchangeUnits int = 0
	for i := 0; i < len(buyers); i++ {
		exchangeUnits += buyers[i].Quantities
		if clearedUnits-exchangeUnits >= 0 {
			buyersPay[i] = clearedPrice * float64(buyers[i].Quantities)
		}
		if clearedUnits-exchangeUnits == 0 {
			buyersPay[i] = clearedPrice * float64(buyers[i].Quantities)
			break
		}
		if clearedUnits-exchangeUnits < 0 {
			buyersPay[i] = clearedPrice * float64(exchangeUnits-clearedUnits)
			break
		}
	}

	exchangeUnits = 0
	for i := 0; i < len(sellers); i++ {
		exchangeUnits += sellers[i].Quantities
		if clearedUnits-exchangeUnits > 0 {
			sellersPay[i] = clearedPrice * float64(sellers[i].Quantities)
		}
		if clearedUnits-exchangeUnits == 0 {
			sellersPay[i] = clearedPrice * float64(sellers[i].Quantities)
			break
		}
		if clearedUnits-exchangeUnits < 0 {
			sellersPay[i] = clearedPrice * float64(exchangeUnits-clearedUnits)
			break
		}
	}
	logger.Error("-----------------------------------------")
	logger.Error("buyersPay", buyersPay[:])
	logger.Error("-----------------------------------------")
	logger.Error("-----------------------------------------")
	logger.Error("sellersPay", sellersPay[:])
	logger.Error("-----------------------------------------")
	return buyersPay[:], sellersPay[:], clearedUnits, clearedPrice
}

func FindIndex(addr string, k int, sellers [3][]SellerBid) int {
	for i := 0; i < len(sellers[0]); i++ {
		if addr == sellers[k][i].Address {
			return i
		}
	}
	return -1
}

func FindBuyer(addr string, buyers []BuyerBid) int {
	for i := 0; i < len(buyers); i++ {
		if addr == buyers[i].Address {
			return i
		}
	}
	return -1
}

func ChangeBalance(addr string, fee float64, accounts *Accounts) {
	index := -1
	for i := 0; i < len(accounts.Address); i++ {
		if addr == accounts.Address[i] {
			index = i
			break
		}
	}
	if index != -1 {
		accounts.Balance[index] += fee
	}
}

func StrToIntArr(s string) []int {
	res := []int{}
	ss := strings.Split(s, ",")
	for _, v := range ss {
		tmp, _ := strconv.Atoi(v)
		res = append(res, tmp)
	}
	return res
}

func StrToFloatArr(s string) []float64 {
	res := []float64{}
	ss := strings.Split(s, ",")
	for _, v := range ss {
		tmp, _ := strconv.ParseFloat(v, 64)
		res = append(res, tmp)
	}
	return res
}

func Sum(arr []float64) float64 {
	res := 0.0
	for i := 0; i < len(arr); i++ {
		res += arr[i]
	}
	return res
}

func Hash(s string) string {
	h := sha1.New()
	h.Write([]byte(s))
	sha1_hash := hex.EncodeToString(h.Sum(nil))
	return sha1_hash
}

func Min(x, y int) int {
	if x < y {
		return x
	}
	return y
}
