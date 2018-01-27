
# coding: utf-8

# In[ ]:


# Parameters
# Modify secrets.sample.json with your Bittrex key and secret, and rename to secrets.json
flip=0.01
waittrade=43200 # 12 hours to wait for a trade to complete
marketcharge=0.0025
market="ETH-NEO"


# In[ ]:


# Enable Logging
import logging

# create logger
logger = logging.getLogger('BittrexFlipper')
logger.setLevel(logging.DEBUG)
# create file handler which logs even debug messages
fh = logging.FileHandler('flipper.log')
fh.setLevel(logging.DEBUG)
# create console handler
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
# create formatter and add it to the handlers
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
fh.setFormatter(formatter)
ch.setFormatter(formatter)
# add the handlers to the logger
logger.addHandler(fh)
logger.addHandler(ch)
logger.info("Starting BittrexFlipper")


# In[ ]:


# Trade Initialization
from bittrex import *
import json
from time import sleep
import sys
from datetime import datetime
from dateutil import parser

logger.info("Logging into Bittrex")
try:
    with open("secrets.json") as secrets_file:
        secrets = json.load(secrets_file)
        secrets_file.close()
    mybit = Bittrex(secrets['key'], secrets['secret'])
    # Confirm we are logged in by pulling all balances
    balances=mybit.get_balances()
    if (balances['success']==False):
        raise ValueError(balances['message'])
except Exception as e:
    logger.error("Error while trying to log into Bittrex. Exiting.")
    logger.debug(e)
    sys.exit(1)
logger.info("Logged into Bittrex successfully")


# In[ ]:


logger.info("Initializing trading conditions")
logger.info("flip="+str(flip))
logger.info("market_charge="+str(marketcharge))
logger.info("market="+market)
openorders=mybit.get_open_orders(market)['result']
neoquantity=mybit.get_balance('NEO')['result']['Available']
logger.info("NEO quantity="+str(neoquantity))
ethquantity=mybit.get_balance('ETH')['result']['Available']
logger.info("ETH quantity="+str(ethquantity))
#mylastorderlimit=mybit.get_order_history(market)['result'][0]['Limit']
#logger.info("mylastorderlimit="+str(mylastorderlimit))
lastneosell=mybit.get_orderbook(market,depth_type='sell',depth=1)['result'][0]['Rate']
logger.info("lastneosell="+str(lastneosell))
lastneobuy=mybit.get_orderbook(market,depth_type='buy',depth=1)['result'][0]['Rate']
logger.info("lastneobuy="+str(lastneobuy))

# startbuy is a semaphore to control whether we create a buy_limit first if True. Default to False.
startbuy=False

# existingorder is a semaphore to control whether we have an existing order at startup. Default to False
existingorder=False
orderuuid=""

# if we have a single previous open position, resume from here:
if (len(openorders)==1):
    existingorder=True
    orderuuid=openorders[0]['OrderUuid']
    initialrate=openorders[0]['Limit']
    # If sell_limit - find order uuid, set rate=order['Limit'], wait for bid to close, and then resume loop here
    if (openorders[0]['OrderType']=='LIMIT_SELL'):
        logger.warn("There is an existing LIMIT_SELL order uuid="+orderuuid)
        startbuy=False
    # If ask_limit - find order uuid, set rate=order['Limit'], and wait for ask to close, and then resume loop here
    elif (openorders[0]['OrderType']=='LIMIT_BUY'):
        logger.warn("There is an existing LIMIT_BUY order uuid="+orderuuid)
        startbuy=True
    else:
        logger.error("There is an unexpected open order that is neither LIMIT_SELL or LIMIT_BUY. Exiting.")
        sys.exit(2)
elif (len(openorders)==0):
    # Determine if we are buying or selling first based on which coin we have more of
    if(neoquantity>ethquantity):
        logger.info("Found more NEO than ETH. Selling NEO for ETH.")
        startbuy=False
        # Sell high
        # Determine the initial rate to sell at based on the market (we are long NEO)
        initialrate=lastneosell
    else:
        logger.info("Found less NEO than ETH. Buying NEO with ETH.")
        logger.error("The bittrex python api no longer supports get_order_history() and we cannot proceed safely. Manually create an open order and start flipper again.")
        sys.exit(100)
        # The rest of the code is dead until this bug is fixed in the bittrex python library 
        startbuy=True
        # Buy low
        # Determine the initial rate to buy at based on the smaller of either the current rate or the last order we closed (long NEO)
        if(lastneobuy>mylastorderlimit):
            initialrate=mylastorderlimit
        else:
            initialrate=lastneobuy
#if we have more than one previous open positions, error out
else:
    logger.error("There are multiple open orders. Exiting.")
    sys.exit(1)

logger.info("startbuy="+str(startbuy))
logger.info("existingorder="+str(existingorder))
logger.info("orderuuid="+orderuuid)
logger.info("initialrate="+str(initialrate))
rate=initialrate


# In[ ]:


# Helper Functions
def spinning_cursor():
    while True:
        for cursor in '|/-\\':
            yield cursor

spinner = spinning_cursor()


# In[ ]:


# Main Trade Loop
logger.info("Starting Main Trade Loop")
while True:
    # Sell Limit Order
    if not startbuy:
        # Keep trying to sell until it goes through
        selling=True
        while selling:
            logger.info("Sell Limit Order")
            if not existingorder:
                rate=rate*(1+flip+marketcharge)
                logger.debug("rate=rate*(1+flip+marketcharge)=rate*(1+"+str(flip+marketcharge)+")="+str(rate))
                while True:
                    try:
                        neoquantity=float(mybit.get_balance('NEO')['result']['Available'])
                        logger.info("Placing Sell Limit on market="+market+"for neoquantity="+str(neoquantity)+" NEO at rate="+str(rate))                    
                        sleep(3)
                        sellresult=mybit.sell_limit(market,neoquantity,rate)
                        orderuuid=sellresult['result']['uuid']
                        break
                    except Exception as e:
                        logger.error("Exception while trying to place order, trying again")
                        logger.debug(e)
                        pass
            else:
                logger.info("Resuming existing order")
            # Always clear the existingorder semaphore if initialized
            existingorder=False
            order_opened=mybit.get_order(orderuuid)['result']['Opened']
            logger.info("Found Order UUID="+orderuuid+" opened on "+order_opened+". Waiting for close.")
            
            # Wait until trade close loop
            while True:
                try:
                    # Initialize our wait to 0 seconds timedelta
                    waited=datetime.utcnow()-datetime.utcnow()
                    while mybit.get_order(orderuuid)['result']['IsOpen']:
                        selling=True
                        waited=datetime.utcnow()-parser.parse(order_opened)
                        if(waited.total_seconds()>waittrade):
                            logger.warn("Waited longer than "+str(waittrade)+" seconds, cancelling order "+orderuuid)
                            try:
                                ordercancel=mybit.cancel(uuid=orderuuid)
                                if(ordercancel['success']!=True):
                                    raise ValueError(ordercancel['message'])
                                else:
                                    logger.info("Successfully cancelled order "+orderuuid)
                                    lastneosell=mybit.get_orderbook(market,depth_type='sell',depth=1)['result'][0]['Rate']
                                    rate=lastneosell
                                    # Note - the rate will increase by flip+marketcharge on the next pass
                                    logger.info("Adjusting new rate to lastneosell="+str(rate))
                                    # Ensure selling is True to try again
                                    selling=True
                                    # break out of the wait for trade close loop
                                    break
                            except Exception as e:
                                logger.error("Exception while attempting to cancel order "+orderuuid+" and setting the new rate. Exiting!")
                                logger.debug(e)
                                sys.exit(3)
                        else:
                            sys.stdout.write(spinner.next())
                            sys.stdout.flush()
                            sleep(3)
                            sys.stdout.write('\b')
                            # Set selling to false in assumption that it may be complete
                            selling=False
                    print("")
                    # If we see that the order was cancelled when we did not, exit out
                    if (mybit.get_order(orderuuid)['result']['CancelInitiated']) and not selling:
                        logger.error("Order cancelled unexpectedly! Exiting.")
                        sys.exit(2)
                    elif not selling:
                        logger.info("Sell Order "+orderuuid+" closed successfully!")
                        logger.debug("Waited "+str(waited)+" to close order "+orderuuid)
                    # Break out of the wait loop if we successfully make it here
                    break
                except Exception as e:
                    logger.error("Exception while trying to get order status, trying again")
                    logger.debug(e)
                    # Reattempt
                    pass

    # Buy Limit Order
    # Always clear the startbuy semaphore if initialized
    startbuy=False
    print("INFO: Buy Limit Order")
    if not existingorder:
        rate=rate*(1-flip-marketcharge)
        logger.debug("rate=rate*(1-flip-marketcharge)=rate*(1-"+str(flip-marketcharge)+")="+str(rate))
        while True:
            try:
                ethquantity=float(mybit.get_balance('ETH')['result']['Available'])
                buyquantity=(ethquantity*(1-marketcharge))/rate
                logger.info("Placing Buy Limit on market="+market+" for buyquantity="+str(buyquantity)+" NEO at rate="+str(rate))
                sleep(3)
                buyresult=mybit.buy_limit(market,buyquantity,rate)
                orderuuid=buyresult['result']['uuid']
                break
            except Exception as e:
                logger.error("Exception while trying to place the order, trying again")
                logger.debug(e)
                pass
    else:
        print("INFO: Resuming existing order")
    # Always clear the existingorder semaphore if initialized
    existingorder=False
    order_opened=mybit.get_order(orderuuid)['result']['Opened']
    logger.info("Found Order UUID="+orderuuid+" opened on "+order_opened+". Waiting for close.")
    while True:
        try:
            while mybit.get_order(orderuuid)['result']['IsOpen']:
                sys.stdout.write(spinner.next())
                sys.stdout.flush()
                sleep(3)
                sys.stdout.write('\b')
            print("")
            if (mybit.get_order(orderuuid)['result']['CancelInitiated']):
                logger.error("Order cancelled unexpectedly! Exiting.")
                sys.exit(2)
            else:
                logger.info("Buy Order closed!")
            break
        except Exception as e:
            logger.error("Exception while trying to get order status, trying again")
            logger.debug(e)
            pass

