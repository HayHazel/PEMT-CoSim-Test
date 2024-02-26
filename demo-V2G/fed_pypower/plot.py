import pandas as pd
import plotly.express as px

data = pd.read_csv('NonGLDLoad.txt')

# data = data[["LMP_P7"]]


px.line(data).write_image("plot.svg")
