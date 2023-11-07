import gzip
import json
import time
import pprint
from datetime import datetime
from pandas import json_normalize
import pandas as pd
import websocket
from scipy.optimize import minimize
import numpy as np
import matplotlib.pyplot as plt

def on_open(ws):
    data = {
        "req": "market." + ticker + ".kline.60min",
        "id": "id1",
        "from": int(time.mktime(datetime.strptime("2023-09-01 00:00:00", "%Y-%m-%d %H:%M:%S").timetuple())),
        "to": int(time.mktime(datetime.strptime("2023-09-01 23:00:00", "%Y-%m-%d %H:%M:%S").timetuple()))}
    send_message(ws, data)

def send_message(ws, message_dict):
    data = json.dumps(message_dict).encode()
    print("Sending Message:")
    pprint.pprint(message_dict)
    ws.send(data)

def on_message(ws, message):
    unzipped_data = gzip.decompress(message).decode()
    msg_dict = json.loads(unzipped_data)
    print("Recieved Message: ")
    pprint.pprint(msg_dict)
    data_output.append(msg_dict)
    if 'ping' in msg_dict:
        data = {
            "pong": msg_dict['ping']
        }
        send_message(ws, data)
        on_close(ws)
        print("Closing Connection")

def on_error(ws, error):
    print("Error: " + str(error))
    error = gzip.decompress(error).decode()
    print(error)
    
def on_close(ws):
    ws.close()
    print("### Connection closed ###")

def createDf():
    cleaned_df = []
    for j in data_output:
        if 'data' in j.keys():
            df = json_normalize(j['data'])
            df['datetime'] = pd.to_datetime(df.id, unit = 's') + pd.Timedelta(hours = 8)
            df['asset'] = list(set(j['rep'].split(".")).intersection(["btcusdt", "ethusdt", "ltcusdt"]))[0]
            cleaned_df.append(df)

    df = pd.concat(cleaned_df)
    portfolio1 = pd.pivot(df[["close", "datetime", "asset"]], index='datetime', columns = 'asset', values='close')
    
    return portfolio1, portfolio1.pct_change().dropna()

def efficientFrontier(df, ret, std):
    """
    To compute the efficient frontier: 
    1) Fix a target return level and minimize volatility for each target return
    2) Fix volatility level and maximize return for each target volatility
    """
    output_arr_min_var = []
    ret_out = []
    targetRangeRet = np.linspace(-0.01, 0.01, 500)
    portWeights = []
    
    def portfolio_returns(weights):
        return (np.sum(ret * weights))

    def portfolio_sd(weights):
        return np.sqrt(np.transpose(weights) @ (std) @ weights)

    def sharpe(weights):
        return (portfolio_returns(weights) / portfolio_sd(weights))

    def minimumVarOpt(constraints = None):
        """
        Minimum Variance Portfolio Optimization
        
        Parameters
        ----------
        nAssets : int, number of assets

        Returns
        -------
        list of portfolio weights
        """
        if constraints is not None:
            constraints = constraints
        else:
            constraints = ({'type': 'eq', 'fun': lambda x: np.sum(x) - 1})
        
        nAssets = df.shape[1]
        bounds = tuple(
            (0, 1) for j in range(nAssets)
        )
        eq_wts = np.array([1 / nAssets] * nAssets)

        min_var = minimize(
            fun = portfolio_sd, 
            x0 = eq_wts,
            method = 'SLSQP',
            bounds = bounds,
            constraints = constraints,
            options={'maxiter':300}
        )
        return min_var
    
    for target_return in targetRangeRet:
        constraints_min_var = (
            {'type': 'eq', 'fun': lambda x: portfolio_returns(x) - target_return}, 
            {'type': 'eq', 'fun': lambda x: np.sum(x) - 1}
        )
        res_out = minimumVarOpt(constraints=constraints_min_var)
        if res_out['success']:
            output_arr_min_var.append(res_out['fun'])
            ret_out.append(target_return)
            weights = res_out['x'].tolist()
            weights.append(sharpe(res_out['x']))
            weights.append(portfolio_sd(res_out['x']))
            portWeights.append(weights)
        else:
            break
    
    wsCol = df.columns.to_list()
    wsCol.append('SharpeRatio')
    wsCol.append('SD')
    weightsAndSharpe = pd.DataFrame(portWeights, columns = wsCol)

    return output_arr_min_var, ret_out, weightsAndSharpe

def generateRandPorts(df_returns):
    returns_list = []
    vol_list = []
    wts_list = []
    expRet = df_returns.mean().values * 100
    data_cov = (df_returns * 100).cov()

    fnt_size = 10

    for i in range(10000):
        wts = np.random.random(3)
        norm_wts = wts / np.sum(wts)
        wts_list.append(norm_wts)

        randPortReturn = expRet.dot(norm_wts)
        returns_list.append(randPortReturn)
        
        randPortVar = np.dot(np.dot(norm_wts.T, data_cov), norm_wts)
        randPortStd = np.sqrt(randPortVar)
        vol_list.append(randPortStd)

    ports = pd.DataFrame({'Return':returns_list, 'Vol':vol_list})
    wts_df = pd.DataFrame(np.vstack(tuple(wts_list)), columns=['btcusdt', 'ethusdt', 'ltcusdt'])
    rand_ports = pd.concat([ports, wts_df], axis=1)

    frontier1 = rand_ports.sort_values(by='Vol')[["Return", "Vol"]].rolling(250).max().dropna().rolling(100).mean()

    fig, ax = plt.subplots(1, 1, figsize=(12, 8), constrained_layout=True)

    ax.scatter(ports.Vol, ports.Return)
    ax.plot(frontier1.Vol, frontier1.Return, color = 'red')
    ax.set_xlabel("Expected Vol (%)", fontsize=fnt_size)
    ax.set_ylabel("Expected Return (%)", fontsize=fnt_size)
    ax.xaxis.set_tick_params(which='both', labelbottom=True, labelsize=fnt_size)
    ax.yaxis.set_tick_params(which='both', labelbottom=True, labelsize=fnt_size)

    fig.suptitle("Random Portfolios")
    fig.savefig("efficient_frontier.png")


    return None

data_output = []
ticker_list = ["btcusdt", "ethusdt", "ltcusdt"]
for ticker in ticker_list:
    try:
        ws = websocket.WebSocketApp(
            "wss://api.huobi.pro/ws",
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )
        ws.run_forever()
    except Exception:
        print("error")

df, df_returns = createDf()
print(df)
returns = (1 + df_returns).prod() - 1
stdev = (df_returns).cov()

vol, ret, w_s = efficientFrontier(df=df, ret=returns, std=stdev)





